# tests/test_agent_loop.py
import json

import pytest

from app.agent.llm import LLMError, LLMResponse, ScriptedLLM, ToolCallRequest
from app.agent.loop import AgentRunner
from app.agent.tools import ToolRegistry, ToolSpec
from app.agent.trace import Tracer


def call(call_id, name, arguments=None):
    return ToolCallRequest(id=call_id, name=name, arguments=arguments or {})


def build_registry(counter=None):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="list_my_documents",
            description="列出文档",
            parameters={"type": "object", "properties": {}},
            func=lambda: {"items": [{"id": 1, "filename": "a.txt"}]},
        )
    )

    def boom():
        if counter is not None:
            counter.append("boom")
        raise RuntimeError("工具内部错误")

    def other():
        if counter is not None:
            counter.append("other")
        return {"items": []}

    registry.register(
        ToolSpec(name="boom", description="总是失败", parameters={"type": "object", "properties": {}}, func=boom)
    )
    registry.register(
        ToolSpec(name="other", description="另一个工具", parameters={"type": "object", "properties": {}}, func=other)
    )
    return registry


def runner(script, **kwargs):
    llm = ScriptedLLM(script)
    kwargs.setdefault("max_steps", 4)
    return AgentRunner(llm=llm, tools=build_registry(kwargs.pop("counter", None)), **kwargs), llm


def test_direct_answer_without_tools():
    agent, _ = runner([LLMResponse(content="你好，我是知识库助手")])

    result = agent.run("在吗")

    assert result.stopped_reason == "completed"
    assert result.steps == 1
    assert result.answer == "你好，我是知识库助手"
    kinds = [event["kind"] for event in result.trace]
    assert kinds[0] == "run_start"
    assert kinds[-1] == "run_end"


def test_multi_step_tool_use_feeds_observation_back():
    agent, llm = runner(
        [
            LLMResponse(tool_calls=[call("c1", "list_my_documents")]),
            LLMResponse(content="你只有 1 篇文档 a.txt"),
        ]
    )

    result = agent.run("我有哪些文档")

    assert result.stopped_reason == "completed"
    assert result.steps == 2
    # 第二次请求模型时，上下文里必须带上工具的真实返回
    second_round_messages = llm.calls[1]["messages"]
    tool_messages = [m for m in second_round_messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "a.txt" in tool_messages[0]["content"]
    assert tool_messages[0]["tool_call_id"] == "c1"
    # 工具声明被一起传给了模型
    assert llm.calls[0]["tools"][0]["function"]["name"] == "list_my_documents"


def test_tool_failure_becomes_observation_and_run_continues():
    agent, llm = runner(
        [
            LLMResponse(tool_calls=[call("c1", "boom")]),
            LLMResponse(content="刚才的工具挂了，我换个说法"),
        ]
    )

    result = agent.run("查一下")

    assert result.stopped_reason == "completed"
    tool_messages = [m for m in llm.calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_messages[0]["content"].startswith("[tool_error]")
    tool_events = [event for event in result.trace if event["kind"] == "tool_call"]
    assert tool_events[0]["ok"] is False
    assert "工具内部错误" in tool_events[0]["error"]


def test_budget_exhausted_stops_at_max_steps():
    agent, llm = runner(
        [LLMResponse(tool_calls=[call(f"c{i}", "list_my_documents")]) for i in range(5)],
        max_steps=2,
    )

    result = agent.run("一直查")

    assert result.stopped_reason == "max_steps"
    assert result.steps == 2
    assert "预算" in result.answer
    assert len(llm.calls) == 2
    assert any(event["kind"] == "budget_exhausted" for event in result.trace)


def test_llm_error_is_downgraded():
    agent, _ = runner([LLMError("连接超时")])

    result = agent.run("你好")

    assert result.stopped_reason == "llm_error"
    assert "暂时不可用" in result.answer
    assert result.trace[-1]["kind"] == "run_end"
    assert any(event["kind"] == "llm_error" for event in result.trace)


def test_empty_content_is_replaced():
    agent, _ = runner([LLMResponse(content="   ")])

    result = agent.run("你好")

    assert result.answer == "（模型没有返回内容）"


def test_empty_question_is_rejected():
    agent, _ = runner([LLMResponse(content="x")])

    with pytest.raises(ValueError):
        agent.run("   ")


def test_trace_is_written_as_jsonl(tmp_path):
    tracer = Tracer.with_path_dir(tmp_path)
    agent, _ = runner(
        [
            LLMResponse(tool_calls=[call("c1", "list_my_documents")]),
            LLMResponse(content="完成"),
        ],
        tracer=tracer,
    )

    result = agent.run("我有哪些文档")

    assert tracer.write_errors == 0
    trace_file = tmp_path / f"{result.run_id}.jsonl"
    assert trace_file.exists()
    lines = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["kind"] == "run_start"
    assert lines[-1]["kind"] == "run_end"
    assert lines[-1]["summary"]["tool_calls"] == 1
    assert all(line["run_id"] == result.run_id for line in lines)


def test_long_tool_arguments_are_truncated_in_trace():
    agent, _ = runner(
        [
            LLMResponse(tool_calls=[call("c1", "list_my_documents", {"query": "长" * 200})]),
            LLMResponse(content="完成"),
        ]
    )

    result = agent.run("查")

    tool_event = next(event for event in result.trace if event["kind"] == "tool_call")
    assert tool_event["arguments"]["query"].endswith("...")
    assert len(tool_event["arguments"]["query"]) == 83


def test_extra_tool_calls_per_step_are_dropped():
    counter = []
    agent, _ = runner(
        [
            LLMResponse(tool_calls=[call("c1", "boom"), call("c2", "other")]),
            LLMResponse(content="完成"),
        ],
        counter=counter,
        max_tool_calls_per_step=1,
    )

    result = agent.run("一次调两个")

    assert counter == ["boom"]
    assert any(event["kind"] == "tool_calls_truncated" for event in result.trace)
