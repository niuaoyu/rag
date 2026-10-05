"""按字符滑窗切块，保留页码，尽量在段落/句子边界断开。"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.parsing import ParsedPage

_BREAKS = ["\n\n", "\n", "。", "！", "？", ". ", "；", ";", " "]


@dataclass
class TextChunk:
    content: str
    page: int | None
    ordinal: int


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            cut = -1
            for br in _BREAKS:
                pos = window.rfind(br)
                if pos > size * 0.5:
                    cut = pos + len(br)
                    break
            if cut > 0:
                end = start + cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunk_pages(pages: list[ParsedPage]) -> list[TextChunk]:
    size, overlap = settings.chunk_size, settings.chunk_overlap
    chunks: list[TextChunk] = []
    ordinal = 0
    for page in pages:
        for piece in _split_long(page.text, size, overlap):
            chunks.append(TextChunk(content=piece, page=page.page, ordinal=ordinal))
            ordinal += 1
    return chunks
