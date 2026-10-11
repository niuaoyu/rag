"""M8：LLM 客户端（OpenAI 兼容 /chat/completions）。

为什么不引厂商 SDK：我们只用到"一个 POST + 解析 JSON"，
引 SDK 会带来版本锁定和多厂商适配成本；httpx 自己打反而更好测（可以用 MockTransport 假造服务端）。
在什么条件下会输：要接非 OpenAI 兼容协议（如原生 Anthropic）或多模态/function calling 复杂场景时，
自写客户端的维护成本会超过 SDK 的收益 —— 那时候应该换 SDK。
"""

from __future__ import annotations

import json
from typing import Iterator, Protocol

import httpx

from app.core.config import settings as default_settings


class LLMError(Exception):
    pass


class LLMNotConfigured(LLMError):
    """没有配 key。上层据此返回 mode=retrieval_only，而不是伪造一个答案。"""


class BaseLLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...

    def stream(self, system: str, user: str) -> Iterator[str]: ...


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMNotConfigured("llm_api_key 为空")
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "stream": stream,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.post("/chat/completions", json=self._payload(system, user, False))
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 调用失败: {type(exc).__name__}: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 返回格式不符合预期: {response.text[:200]}") from exc

    def stream(self, system: str, user: str) -> Iterator[str]:
        """SSE 增量输出。解析 openai 风格的 `data: {...}` 行。"""
        try:
            with self._client.stream(
                "POST", "/chat/completions", json=self._payload(system, user, True)
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 流式调用失败: {type(exc).__name__}: {exc}") from exc


def build_llm(cfg=default_settings) -> BaseLLM:
    if not cfg.llm_api_key:
        raise LLMNotConfigured("未配置 llm_api_key")
    return OpenAICompatLLM(
        base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key,
        model=cfg.llm_model,
        temperature=cfg.llm_temperature,
        timeout=cfg.llm_timeout_seconds,
    )
