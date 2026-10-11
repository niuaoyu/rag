"""M8：检索增强生成（RAG）——把检索到的块拼成带编号的上下文，让模型只依据上下文回答。

三条硬约束（面试会被追问）：
1. **没检索到就不许答**：没有上下文时直接返回 mode=no_context，不让模型自由发挥（幻觉的最大来源）。
2. **没配 key 就不许伪造**：mode=retrieval_only 只回检索结果；不拿模板文本冒充"AI 回答"。
3. **答案必须带来源**：上下文按 [1][2] 编号，回答里的引用编号能对回到 chunk_id / 文件名 / 块序号。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings as default_settings
from app.services.llm import BaseLLM, LLMError, LLMNotConfigured, build_llm
from app.services.retrieval import RetrievedChunk, search_chunks

SYSTEM_PROMPT = (
    "你是一个只依据给定资料回答问题的助手。\n"
    "规则：\n"
    "1. 只能使用【资料】中的内容回答，不得引入资料之外的任何事实。\n"
    "2. 在引用某段资料时，在该句末尾用方括号标注编号，例如 [1]、[1][3]。\n"
    "3. 如果【资料】不足以回答问题，直接回答：根据已有资料无法回答该问题。\n"
    "4. 用简体中文回答，简洁，不要复述资料原文超过 2 句。"
)

SNIPPET_CHARS = 120


@dataclass(frozen=True)
class Citation:
    index: int
    chunk_id: int
    document_id: int
    filename: str
    ordinal: int
    score: float
    snippet: str


@dataclass
class RagAnswer:
    question: str
    answer: str | None
    mode: str  # llm | retrieval_only | no_context
    citations: list[Citation] = field(default_factory=list)
    retrieved_count: int = 0
    latency_ms: int = 0
    note: str | None = None


def build_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        blocks.append(f"[{i}] 来源：{chunk.filename}（第 {chunk.ordinal + 1} 块）\n{chunk.text}")
    return "\n\n".join(blocks)


def build_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            index=i,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            filename=chunk.filename,
            ordinal=chunk.ordinal,
            score=round(chunk.score, 4),
            snippet=chunk.text[:SNIPPET_CHARS],
        )
        for i, chunk in enumerate(chunks, start=1)
    ]


def build_user_prompt(question: str, context: str) -> str:
    return f"【资料】\n{context}\n\n【问题】\n{question}\n\n请依据资料回答，并标注引用编号。"


def answer_question(
    db: Session,
    user_id: int,
    question: str,
    top_k: int | None = None,
    llm: BaseLLM | None = None,
    cfg=default_settings,
) -> RagAnswer:
    started = time.perf_counter()
    question = (question or "").strip()
    if not question:
        raise ValueError("question 不能为空")

    chunks = search_chunks(db, user_id, question, top_k=top_k, cfg=cfg)
    citations = build_citations(chunks)
    elapsed = lambda: int((time.perf_counter() - started) * 1000)  # noqa: E731

    if not chunks:
        return RagAnswer(
            question=question,
            answer=None,
            mode="no_context",
            citations=[],
            retrieved_count=0,
            latency_ms=elapsed(),
            note="没有检索到任何相关片段，未调用模型（避免无依据编造）。",
        )

    if llm is None:
        try:
            llm = build_llm(cfg)
        except LLMNotConfigured as exc:
            return RagAnswer(
                question=question,
                answer=None,
                mode="retrieval_only",
                citations=citations,
                retrieved_count=len(chunks),
                latency_ms=elapsed(),
                note=f"未配置 LLM（{exc}），仅返回检索结果。",
            )

    try:
        answer = llm.complete(SYSTEM_PROMPT, build_user_prompt(question, build_context(chunks)))
    except LLMError as exc:
        return RagAnswer(
            question=question,
            answer=None,
            mode="retrieval_only",
            citations=citations,
            retrieved_count=len(chunks),
            latency_ms=elapsed(),
            note=f"模型调用失败，已降级为只回检索结果：{exc}",
        )

    return RagAnswer(
        question=question,
        answer=answer.strip(),
        mode="llm",
        citations=citations,
        retrieved_count=len(chunks),
        latency_ms=elapsed(),
    )
