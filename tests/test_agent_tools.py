# tests/test_agent_tools.py
import time

import pytest

from app.agent.tools import ToolError, ToolRegistry, ToolSpec


def _echo_spec(**overrides):
    params = {
        "name": "echo",
        "description": "回显文本",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        "func": lambda text: {"echo": text},
    }
    params.update(overrides)
    return ToolSpec(**params)


def test_register_exports_openai_function_schema():
    registry = ToolRegistry()
    registry.register(_echo_spec())

    specs = registry.specs()

    assert len(specs) == 1
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "echo"
    assert specs[0]["function"]["parameters"]["required"] == ["text"]
    assert registry.names() == ("echo",)
    assert "echo" in registry.describe()


def test_duplicate_name_is_rejected():
    registry = ToolRegistry()
    registry.register(_echo_spec())
    with pytest.raises(ToolError):
        registry.register(_echo_spec())


def test_unknown_tool_becomes_failed_result():
    registry = ToolRegistry()
    registry.register(_echo_spec())

    result = registry.execute("delete_everything", {})

    assert result.ok is False
    assert "未知工具" in result.error


def test_non_object_arguments_are_rejected():
    registry = ToolRegistry()
    registry.register(_echo_spec())

    result = registry.execute("echo", ["text"])

    assert result.ok is False
    assert "必须是对象" in result.error


def test_tool_exception_is_captured_not_raised():
    def boom():
        raise ValueError("内部炸了")

    registry = ToolRegistry()
    registry.register(_echo_spec(name="boom", description="总是失败", func=boom))

    result = registry.execute("boom", {})

    assert result.ok is False
    assert result.error.startswith("ValueError")
    assert "内部炸了" in result.error


def test_missing_required_argument_is_captured():
    registry = ToolRegistry()
    registry.register(_echo_spec())

    result = registry.execute("echo", {})

    assert result.ok is False
    assert "TypeError" in result.error


def test_tool_timeout_is_bounded():
    def slow():
        time.sleep(1.0)
        return "done"

    registry = ToolRegistry()
    registry.register(_echo_spec(name="slow", description="慢工具", func=slow, timeout_seconds=0.05))

    begin = time.perf_counter()
    result = registry.execute("slow", {})
    elapsed = time.perf_counter() - begin

    assert result.ok is False
    assert "超过" in result.error
    assert elapsed < 0.8  # 不会等工具睡满 1 秒


def test_execute_timeout_can_be_overridden_per_call():
    def slow():
        time.sleep(1.0)
        return "done"

    registry = ToolRegistry()
    registry.register(_echo_spec(name="slow", description="慢工具", func=slow, timeout_seconds=30))

    result = registry.execute("slow", {}, timeout_seconds=0.05)

    assert result.ok is False


def test_long_observation_is_truncated():
    registry = ToolRegistry()
    registry.register(_echo_spec(func=lambda text: text * 1))
    registry.register(
        _echo_spec(name="big", description="大结果", func=lambda text: "x" * 5000)
    )

    result = registry.execute("big", {"text": "x"})

    assert result.ok is True
    assert result.content.endswith("(已截断，共 5000 字符)")
    assert result.duration_ms >= 0
