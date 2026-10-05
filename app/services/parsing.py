"""文档解析：PDF（pypdf，带页码）与纯文本。"""
from __future__ import annotations

from dataclasses import dataclass

from pypdf import PdfReader

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedPage:
    page: int | None
    text: str


def parse_pdf(path: str) -> list[ParsedPage]:
    reader = PdfReader(path)
    pages: list[ParsedPage] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(ParsedPage(page=i, text=text))
    logger.info("pdf parsed: %s pages=%d", path, len(pages))
    return pages


def parse_txt(path: str) -> list[ParsedPage]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    logger.info("txt parsed: %s chars=%d", path, len(text))
    return [ParsedPage(page=None, text=text)] if text.strip() else []


def parse_document(path: str, filename: str) -> list[ParsedPage]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return parse_pdf(path)
    if lower.endswith((".txt", ".md", ".markdown")):
        return parse_txt(path)
    raise ValueError(f"不支持的文件类型: {filename}")
