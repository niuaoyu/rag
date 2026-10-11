"""LLM 抽象：mock（离线确定可跑）与 OpenAI 兼容接口（含 SSE 流式与推理参数控制）。"""
from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMError(RuntimeError):
    pass


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }


def _extra_payload() -> dict:
    """推理型网关额外参数：reasoning_effort / max_tokens，空值不传。"""
    extra: dict = {}
    if settings.llm_reasoning_effort:
        extra["reasoning_effort"] = settings.llm_reasoning_effort
    if settings.llm_max_tokens > 0:
        extra["max_tokens"] = settings.llm_max_tokens
    return extra


def _base_payload(messages: list[dict], tools: list[dict] | None) -> dict:
    payload: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
    }
    payload.update(_extra_payload())
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _chat_openai(messages: list[dict], tools: list[dict] | None = None) -> dict:
    if not settings.llm_api_key:
        raise LLMError("LLM_PROVIDER=openai 但未配置 LLM_API_KEY")
    resp = requests.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers=_headers(),
        json=_base_payload(messages, tools),
        timeout=settings.llm_timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """非流式。返回统一格式: {"content": str|None, "tool_calls": [...]}。"""
    if settings.llm_provider == "openai":
        msg = _chat_openai(messages, tools)
        content = msg.get("content")
        tool_calls = msg.get("tool_calls") or []
        if not content and not tool_calls:
            raise LLMError(
                "LLM 返回了空 content（推理型模型常见）。"
                "请设置 LLM_REASONING_EFFORT（如 low）并避免过小的 LLM_MAX_TOKENS。"
            )
        return {"content": content, "tool_calls": tool_calls}
    return _chat_mock(messages, tools)


def chat_stream(messages: list[dict], tools: list[dict] | None = None) -> Iterator[dict]:
    """流式。逐段产出 {"type": "delta", "content": ...}；
    若模型请求工具，产出一次 {"type": "tool_calls", "tool_calls": [OpenAI 格式]}。"""
    if settings.llm_provider != "openai":
        yield from _chat_stream_mock(messages, tools)
        return
    yield from _chat_stream_openai(messages, tools)


def _chat_stream_openai(messages: list[dict], tools: list[dict] | None) -> Iterator[dict]:
    if not settings.llm_api_key:
        raise LLMError("LLM_PROVIDER=openai 但未配置 LLM_API_KEY")
    payload = _base_payload(messages, tools)
    payload["stream"] = True
    yielded = 0
    tool_acc: dict[int, dict] = {}
    with requests.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers=_headers(),
        json=payload,
        timeout=(15, settings.llm_timeout),
        stream=True,
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                yielded += 1
                yield {"type": "delta", "content": delta["content"]}
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_acc.setdefault(idx, {"id": "", "type": "function",
                                                 "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
    if tool_acc:
        yield {"type": "tool_calls", "tool_calls": [tool_acc[k] for k in sorted(tool_acc)]}
        return
    if yielded == 0:
        raise LLMError(
            "LLM 流式返回了空内容（推理型模型常见）。"
            "请设置 LLM_REASONING_EFFORT（如 low）并避免过小的 LLM_MAX_TOKENS。"
        )


def _chat_stream_mock(messages: list[dict], tools: list[dict] | None) -> Iterator[dict]:
    """mock 流式：复用 mock 决策，把答案切成小块逐段输出，保证离线链路与线上一致。"""
    msg = _chat_mock(messages, tools)
    if msg.get("tool_calls"):
        yield {"type": "tool_calls", "tool_calls": msg["tool_calls"]}
        return
    content = msg.get("content") or ""
    step = 20
    for i in range(0, len(content), step):
        yield {"type": "delta", "content": content[i:i + step]}


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

    # 从 system 上下文里提取检索片段（rag service 会把资料块作为 system 消息）
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
