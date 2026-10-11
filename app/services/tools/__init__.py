"""工具注册表：新增工具 = 写一个 schema + 实现，注册到这里即可被 Agent 使用。"""
from __future__ import annotations

from typing import Callable

from app.services.tools.clock import CLOCK_TOOL_SCHEMA, get_current_time
from app.services.tools.weather import WEATHER_TOOL_SCHEMA, get_weather

# name -> (function calling schema, 实现函数)
REGISTRY: dict[str, tuple[dict, Callable]] = {
    "get_weather": (WEATHER_TOOL_SCHEMA, get_weather),
    "get_current_time": (CLOCK_TOOL_SCHEMA, get_current_time),
}

# 提供给 LLM 的 tools 列表（OpenAI function calling 格式）
ALL_TOOL_SCHEMAS = [schema for schema, _ in REGISTRY.values()]


def run_tool(name: str, arguments: dict) -> dict:
    """按名分发工具调用；未知工具抛 ValueError，由 Agent 层捕获为失败记录。"""
    if name not in REGISTRY:
        raise ValueError(f"未知工具: {name}")
    _, fn = REGISTRY[name]
    return fn(**arguments)
