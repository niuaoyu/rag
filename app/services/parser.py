"""M4/M5：把磁盘上的文件变成纯文本。

**纯业务函数，不碰 HTTP，不碰数据库**（M3 的教训：业务逻辑和 HTTPException 混在一起就没法单测）。
失败时抛 ParseError，由上层（app/services/processing.py）决定状态机怎么走。
"""

from __future__ import annotations

from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md"}
PDF_SUFFIXES = {".pdf"}

# 顺序有讲究：先 utf-8，再 utf-8-sig（带 BOM 的 Windows 记事本文件），最后 gbk（老中文文本）
# 为什么不做 chardet 自动探测：多引一个依赖、结果不确定、且我们已知语料只有这三种。
ENCODING_CHAIN = ("utf-8", "utf-8-sig", "gbk")


class ParseError(Exception):
    """解析失败。message 会被写进 documents.error_message。"""


def read_text(path: Path | str) -> str:
    """按编码链依次尝试解码，返回去掉 BOM 的文本。

    为什么"先猜再问"是坏做法：猜错时 utf-8 解码会抛 UnicodeDecodeError，
    而不是给你一段乱码，所以必须显式捕获并换下一个编码。
    """
    p = Path(path)
    raw = p.read_bytes()
    if not raw:
        raise ParseError("文件内容为空")

    for encoding in ENCODING_CHAIN:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        # utf-8 能解码成功但带 BOM 的情况：显式剥掉，否则第一块会多一个不可见字符
        return text.lstrip("\ufeff")

    raise ParseError(f"无法解码文本文件（尝试过 {', '.join(ENCODING_CHAIN)}）")


def read_pdf(path: Path | str) -> str:
    """用 pypdf 抽取每页文本。抽取是尽力而为：扫描版 PDF 抽出来是空串。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ParseError("未安装 pypdf，无法解析 PDF") from exc

    p = Path(path)
    try:
        reader = PdfReader(str(p))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise ParseError(f"PDF 解析失败: {type(exc).__name__}: {exc}") from exc

    text = "\n\n".join(pages).strip()
    if not text:
        raise ParseError("PDF 中未抽取到文本（可能是扫描件/纯图片 PDF）")
    return text


def parse_document(path: Path | str) -> str:
    """按后缀分派。未知后缀直接报错，不猜。"""
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return read_text(path)
    if suffix in PDF_SUFFIXES:
        return read_pdf(path)
    raise ParseError(f"不支持解析的文件类型: {suffix or '<无后缀>'}")
