"""M5：把长文本切成带重叠的块。

两条规则：
1. 尽量不切断语义单元：以段落为单位打包，段落太大才降到句子，句子还太大才硬切字符。
2. 块与块之间留 overlap：跨块的答案（上一段结尾 + 下一段开头）不至于被切断。

为什么单位是 token 而不是字符：embedding 模型和上下文窗口的预算都是 token，
按字符切会让中文文档的块实际 token 数比英文多出 2~3 倍（中英 token/字符比不同）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.tokenizer import count_tokens, truncate_to_tokens

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\.\n])")


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def token_count(self) -> int:
        return count_tokens(self.text)


def _split_oversized(unit: str, size_tokens: int) -> list[str]:
    """段落超过一个块的上限时：先按句子切，句子仍超限就硬切字符。"""
    pieces: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(unit):
        if not sentence:
            continue
        if count_tokens(sentence) <= size_tokens:
            pieces.append(sentence)
            continue
        # 硬切：按估算的 字符/token 比换算步长，保证不会切出超过上限的碎片
        step = max(int(len(sentence) * size_tokens / max(count_tokens(sentence), 1)), 1)
        for i in range(0, len(sentence), step):
            pieces.append(sentence[i : i + step])
    return pieces


def split_units(text: str) -> list[str]:
    """把文本拆成"打包单元"序列（段落优先，超长段落降级为句子/字符片）。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    units: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(normalized):
        paragraph = paragraph.strip()
        if paragraph:
            units.append(paragraph)
    return units


def chunk_text(
    text: str,
    size_tokens: int = 400,
    overlap_tokens: int = 60,
) -> list[ChunkDraft]:
    """切块主函数。空文本返回 []，不返回一个空块。"""
    if not text or not text.strip():
        return []
    if size_tokens <= 0:
        raise ValueError("size_tokens 必须为正数")
    if overlap_tokens >= size_tokens:
        # 不去猜用户意图，直接收紧到安全值：重叠必须明显小于块本身，否则会无限套娃
        overlap_tokens = size_tokens // 4

    units: list[str] = []
    for unit in split_units(text):
        units.extend(_split_oversized(unit, size_tokens))

    chunks: list[ChunkDraft] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        if not body:
            buffer, buffer_tokens = [], 0
            return
        # 重叠部分：把上一块的尾巴接到这一块开头（第一块没有上一块，天然不重叠）
        prefix = ""
        if chunks and overlap_tokens > 0:
            tail = truncate_to_tokens(chunks[-1].text, overlap_tokens)
            if tail and not body.startswith(tail):
                prefix = tail + "\n"
        chunks.append(ChunkDraft(ordinal=len(chunks), text=(prefix + body)))
        buffer, buffer_tokens = [], 0

    for unit in units:
        unit_tokens = count_tokens(unit)
        # 装不下就先封一块；再判断这个单元自己是否已经小于上限（_split_oversized 保证是）
        if buffer and buffer_tokens + unit_tokens > size_tokens:
            flush()
        buffer.append(unit)
        buffer_tokens += unit_tokens
    flush()

    # 重新编号，保证 ordinal 从 0 连续（flush 里用的是 len(chunks)，已经是连续的）
    return [ChunkDraft(ordinal=i, text=c.text) for i, c in enumerate(chunks)]
