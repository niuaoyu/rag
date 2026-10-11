"""M5 切块单测：块大小上界、重叠、序号连续、空文本。

契约（doc/m5切块与检索.md）：
- 每块 token 数 ≤ chunk_size_tokens；含重叠前缀时 ≤ chunk_size_tokens + chunk_overlap_tokens
- 相邻块必须有重叠（否则跨块的答案会被切断）
- ordinal 从 0 连续递增
"""

import pytest

from app.core.tokenizer import count_tokens
from app.services.chunker import chunk_text

PARA = "检索增强生成把外部知识库接进大模型，先检索再生成，答案里带上来源引用。"


def _long_text(paragraphs: int = 30) -> str:
    return "\n\n".join(f"{PARA}（第 {i} 段）" for i in range(paragraphs))


def test_empty_text_returns_no_chunk():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_ordinals_are_contiguous():
    chunks = chunk_text(_long_text(), size_tokens=120, overlap_tokens=20)
    assert len(chunks) > 1
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_each_chunk_respects_size_bound():
    size, overlap = 120, 20
    chunks = chunk_text(_long_text(), size_tokens=size, overlap_tokens=overlap)
    for chunk in chunks:
        assert chunk.token_count <= size + overlap, (chunk.ordinal, chunk.token_count)


def test_adjacent_chunks_overlap():
    chunks = chunk_text(_long_text(), size_tokens=120, overlap_tokens=30)
    assert len(chunks) >= 3
    tail = chunks[0].text[-20:]
    assert tail in chunks[1].text


def test_single_huge_paragraph_is_hard_split():
    """一个没有任何换行的 5000 字段落也必须被切开，不能产出一个超大块。"""
    text = "机器学习" * 1250
    chunks = chunk_text(text, size_tokens=100, overlap_tokens=10)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 110


def test_overlap_not_smaller_than_size_is_clamped():
    """overlap >= size 会让滑动窗口原地打转，必须收紧而不是死循环。"""
    chunks = chunk_text(_long_text(5), size_tokens=100, overlap_tokens=1000)
    assert len(chunks) >= 1
    assert all(c.token_count <= 125 for c in chunks)


def test_invalid_size_raises():
    with pytest.raises(ValueError):
        chunk_text("abc", size_tokens=0)


def test_short_text_is_one_chunk():
    chunks = chunk_text("只有一句话。", size_tokens=400, overlap_tokens=60)
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].token_count == count_tokens("只有一句话。")
