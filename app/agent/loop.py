# app/agent/loop.py
# 编排层：一次问答 = 「模型决策 -> 调工具 -> 把 observation 塞回上下文」的有限步循环。
# 三个边界在这里收口：步数预算、单次工具调用上限、模型错误降级。

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm import LLMClient, LLMError, ToolCallRequest
from app.agent.tools import ToolRegistry
from app.agent.trace import Tracer

DEFAULT_MAX_STEPS = 6
MAX_TOOL_CALLS_PER_STEP = 4
MAX_ARGUMENT_PREVIEW = 80

DEFAULT_SYSTEM_PROMPT = """你是「知识库问答 Agent」，只允许基于工具返回的真实内容回答，禁止编造文档里没有的信息。

工作方式：
1. 用户问「我有哪些文档」这类清单问题时，调用 list_my_documents；
2. 任何涉及文档内容的问题，先用 search_documents 定位，再用 get_document 确认具体条目；
3. 工具返回错误时不要重复同样的调用，换关键词或换个工具再试一次；
4. 查不到就直说没查到，并告诉用户可以怎么问。

回答要求：先用一两句话给结论，再列出用到的文档，格式为「依据：文档 #id 文件名」。"""


@dataclass
class AgentRunResult:
    run_id: str
    answer: str
    steps: int
    stopped_reason: str  # completed / max_steps / llm_error
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "answer": self.answer,
            "steps": self.steps,
            "stopped_reason": self.stopped_reason,
        }


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """写进轨迹前的参数脱敏：长文本只留摘要，避免把用户文档内容整段落盘。"""
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > MAX_ARGUMENT_PREVIEW:
            safe[key] = value[:MAX_ARGUMENT_PREVIEW] + "..."
        else:
            safe[key] = value
    return safe


def _assistant_message(response_content: str | None, calls: list[ToolCallRequest]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response_content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in calls
        ],
    }


class AgentRunner:
    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        max_steps: int = DEFAULT_MAX_STEPS,
        tool_timeout: float | None = None,
        tracer: Tracer | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_calls_per_step: int = MAX_TOOL_CALLS_PER_STEP,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self._llm = llm
        self._tools = tools
        self._max_steps = max_steps
        self._tool_timeout = tool_timeout
        self._tracer = tracer
        self._system_prompt = system_prompt
        self._max_tool_calls_per_step = max_tool_calls_per_step

    def run(self, question: str, *, run_id: str | None = None) -> AgentRunResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("question 不能为空")

        tracer = self._tracer or (Tracer(run_id=run_id) if run_id else Tracer())
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": question},
        ]
        tracer.record(
            "run_start",
            question=question,
            tools=list(self._tools.names()),
            max_steps=self._max_steps,
        )

        steps = 0
        last_content = ""
        for step in range(1, self._max_steps + 1):
            steps = step
            try:
                response = self._llm.complete(messages, self._tools.specs())
            except LLMError as exc:
                tracer.record("llm_error", step=step, error=str(exc))
                return self._finish(
                    tracer,
                    "模型服务暂时不可用，这一轮没有生成回答，请稍后再试。",
                    steps,
                    "llm_error",
                )

            tracer.record(
                "llm_response",
                step=step,
                tool_calls=[call.name for call in response.tool_calls],
                has_content=bool(response.content),
            )

            if not response.tool_calls:
                answer = (response.content or "").strip() or "（模型没有返回内容）"
                return self._finish(tracer, answer, steps, "completed")

            calls = response.tool_calls[: self._max_tool_calls_per_step]
            if len(response.tool_calls) > self._max_tool_calls_per_step:
                tracer.record(
                    "tool_calls_truncated",
                    step=step,
                    dropped=len(response.tool_calls) - self._max_tool_calls_per_step,
                )
            messages.append(_assistant_message(response.content, calls))

            for call in calls:
                result = self._tools.execute(
                    call.name, call.arguments, timeout_seconds=self._tool_timeout
                )
                tracer.record(
                    "tool_call",
                    step=step,
                    call_id=call.id,
                    tool=call.name,
                    arguments=_safe_arguments(call.arguments),
                    ok=result.ok,
                    duration_ms=result.duration_ms,
                    error=result.error,
                    preview=result.content[:200],
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result.content if result.ok else f"[tool_error] {result.error}",
                    }
                )
            if response.content:
                last_content = response.content.strip()

        answer = last_content or (
            f"我在 {self._max_steps} 步工具预算内没有得出结论，可以缩小范围再问一次。"
        )
        tracer.record("budget_exhausted", steps=steps, max_steps=self._max_steps)
        return self._finish(tracer, answer, steps, "max_steps")

    def _finish(self, tracer: Tracer, answer: str, steps: int, stopped_reason: str) -> AgentRunResult:
        tracer.record("run_end", steps=steps, stopped_reason=stopped_reason, summary=tracer.summary)
        return AgentRunResult(
            run_id=tracer.run_id,
            answer=answer,
            steps=steps,
            stopped_reason=stopped_reason,
            trace=tracer.events,
        )

