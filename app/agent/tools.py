# app/agent/tools.py
# 工具层：把一项能力同时声明成「给模型看的 schema」和「真正可执行的函数」，
# 并统一负责参数边界、执行超时和异常收敛。工具内部报错不会打穿到请求层。

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_OBSERVATION_CHARS = 2000


class ToolError(RuntimeError):
    """工具注册或调用约定层面的错误。"""


@dataclass(frozen=True)
class ToolResult:
    """一次工具调用结果。ok=False 时 error 一定有值，content 为空。"""

    ok: bool
    content: str
    error: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    timeout_seconds: float | None = None


def _stringify(value: Any) -> str:
    """把工具返回值压成一段文本 observation，过长就截断，避免塞爆下一轮上下文。"""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > MAX_OBSERVATION_CHARS:
        text = text[:MAX_OBSERVATION_CHARS] + f"...(已截断，共 {len(text)} 字符)"
    return text


def _run_with_timeout(func: Callable[..., Any], kwargs: dict[str, Any], timeout: float) -> Any:
    """在线程里跑工具并限时等待。

    不用线程池：卡死的工具不该占住池里的 worker 让后续调用排队等超时；
    daemon 线程超时后直接放弃，请求本身立刻拿到超时错误。
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def target() -> None:
        try:
            box["value"] = func(**kwargs)
        except BaseException as exc:  # noqa: BLE001 - 工具内部任何异常都收敛成 observation
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=target, name=f"tool-{func.__name__}", daemon=True)
    thread.start()
    if not done.wait(timeout):
        raise ToolError(f"工具执行超过 {timeout}s 未返回")
    if "error" in box:
        raise box["error"]
    return box["value"]


class ToolRegistry:
    """工具注册表：负责白名单校验、schema 导出和执行。"""

    def __init__(self, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._default_timeout = default_timeout

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ToolError(f"工具名重复注册: {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        """导出 OpenAI function calling 格式的工具声明。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    def describe(self) -> str:
        """一行一个工具的人话描述，用于系统提示或排查日志。"""
        return "\n".join(f"- {spec.name}: {spec.description}" for spec in self._tools.values())

    def _resolve_timeout(self, spec: ToolSpec, override: float | None) -> float:
        """超时优先级：调用方指定 > 工具自身声明 > 注册表默认。"""
        if override is not None:
            return override
        if spec.timeout_seconds is not None:
            return spec.timeout_seconds
        return self._default_timeout

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        arguments = arguments or {}
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(ok=False, content="", error=f"未知工具: {name!r}（仅允许 {list(self._tools)}）")
        if not isinstance(arguments, dict):
            return ToolResult(ok=False, content="", error=f"工具参数必须是对象: {arguments!r}")

        timeout = self._resolve_timeout(spec, timeout_seconds)
        begin = time.perf_counter()
        try:
            value = _run_with_timeout(spec.func, arguments, timeout)
        except Exception as exc:  # noqa: BLE001 - 统一收敛成失败 observation
            elapsed = int((time.perf_counter() - begin) * 1000)
            return ToolResult(ok=False, content="", error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed)
        elapsed = int((time.perf_counter() - begin) * 1000)
        return ToolResult(ok=True, content=_stringify(value), duration_ms=elapsed)
