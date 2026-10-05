"""LLM 抽象：mock（离线确定可跑）与 openai 兼容接口。"""
from __future__ import annotations

import json

import requests

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMError(RuntimeError):
    pass


def _chat_openai(messages: list[dict], tools: list[dict] | None = None) -> dict:
    if not settings.llm_api_key:
        raise LLMError("LLM_PROVIDER=openai 但未配置 LLM_API_KEY")
    payload: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = requests.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """返回统一格式: {"content": str|None, "tool_calls": [...]}."""
    if settings.llm_provider == "openai":
        msg = _chat_openai(messages, tools)
        return {
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls") or [],
        }
    return _chat_mock(messages, tools)


def _chat_mock(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """离线 mock：当问题命中工具关键词且允许工具时返回 tool_call，否则基于上下文拼答案。"""
    last = messages[-1]["content"]
    tool_names = {t["function"]["name"] for t in (tools or [])}
    if tools and "get_weather" in tool_names:
        if any(k in last for k in ("天气", "气温", "下雨", "适合户外", "weather")):
            # 抽取城市（简单 demo 规则）
            city = "北京"
            for c in ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安"):
                if c in last:
                    city = c
                    break
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call_mock_weather",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": json.dumps({"city": city}, ensure_ascii=False)},
                }],
            }

    # 从 system 上下文里提取检索片段（rag service 会把资料块作为最后一个 system 消息）
    context = ""
    for m in messages:
        if m["role"] == "system" and m["content"] and "【参考资料】" in m["content"]:
            context = m["content"]
    if context:
        snippet = context.split("【参考资料】", 1)[1]
        lines = [l.strip() for l in snippet.splitlines() if l.strip()][:6]
        body = "\n".join(lines)
    else:
        body = "（未检索到相关文档内容）"
    answer = (
        "以下回答基于你的知识库检索结果：\n\n"
        f"{body}\n\n"
        "（mock 模式输出：配置 LLM_PROVIDER=openai 与 LLM_API_KEY 后，将由真实大模型组织答案。）"
    )
    return {"content": answer, "tool_calls": []}


def summarize_title(question: str) -> str:
    q = question.strip().replace("\n", " ")
    return q[:30] if q else "新会话"
