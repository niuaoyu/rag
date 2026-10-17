# app/agent/llm.py
# 模型接入层：把「调用大模型」收敛成一个可替换的接口。
# 上层（loop.py）只依赖 LLMClient 协议和 LLMResponse，不关心背后是哪家模型。

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx


class LLMError(RuntimeError):
    """模型层错误统一类型：网络、鉴权、响应格式问题都收敛成它，方便上层降级。"""


@dataclass(frozen=True)
class ToolCallRequest:
    """模型要求调用的一次工具。arguments 已经从 JSON 字符串解析成 dict。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@runtime_checkable
class LLMClient(Protocol):
    """模型客户端协议。实现者只要有 complete 方法，测试里可以换成脚本化假模型。"""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


def parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    """把模型返回的 arguments 字符串解析成 dict。

    模型偶尔会给出坏 JSON 甚至数组，这里统一收敛成 LLMError，由上层记一次失败而不是崩掉整个请求。
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"工具参数不是合法 JSON: {raw[:120]}") from exc
    if isinstance(data, dict):
        return data
    return {"value": data}


def parse_chat_response(data: dict[str, Any]) -> LLMResponse:
    """解析 OpenAI 兼容的 /chat/completions 响应体。"""
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"模型响应缺少 choices[0].message: {str(data)[:200]}") from exc

    calls: list[ToolCallRequest] = []
    for index, item in enumerate(message.get("tool_calls") or []):
        function = item.get("function") or {}
        calls.append(
            ToolCallRequest(
                id=item.get("id") or f"call_{index}",
                name=function.get("name") or "",
                arguments=parse_tool_arguments(function.get("arguments")),
            )
        )
    return LLMResponse(content=message.get("content"), tool_calls=calls, raw=data)


class OpenAICompatibleLLM:
    """OpenAI 兼容 /chat/completions 的最小客户端，只依赖 httpx。

    client 参数用于注入（测试里传 httpx.Client(transport=MockTransport(...))），
    不传时每次调用自己建连接，避免长期持有未关闭的会话。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("缺少模型 API Key：请在 .env 里配置 LLM_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = client

    def _send(self, client: httpx.Client, payload: dict[str, Any]) -> httpx.Response:
        return client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] = (),
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        try:
            if self._client is not None:
                response = self._send(self._client, payload)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = self._send(client, payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"模型请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"模型返回 {response.status_code}: {response.text[:200]}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("模型响应不是合法 JSON") from exc
        return parse_chat_response(data)


class ScriptedLLM:
    """测试用假模型：按脚本顺序返回响应，并记录每次收到的 messages / tools。

    脚本元素可以是 LLMResponse，也可以是异常（例如 LLMError），用来验证降级路径。
    脚本用尽后再被调用会直接报错——「模型被多问了一轮」本身就是要暴露的问题。
    """

    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] = (),
    ) -> LLMResponse:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": list(tools)})
        if not self._responses:
            raise LLMError("脚本已用尽：模型被调用的次数超出测试预期")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
