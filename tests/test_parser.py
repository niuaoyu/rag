"""M4/M5 解析层单测：编码兜底、坏文件、PDF。

这一层必须能脱离 HTTP 单测 —— 这就是把 parser 从路由里拆出来的意义（M3 的教训）。
"""

import pytest

from app.services.parser import ParseError, parse_document, read_text


def test_read_utf8_chinese(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes("中文内容：检索增强生成。".encode("utf-8"))
    assert read_text(path) == "中文内容：检索增强生成。"


def test_read_gbk_chinese(tmp_path):
    """老中文 txt 常见 GBK：utf-8 解不开必须能退到 gbk，而不是抛 500。"""
    path = tmp_path / "gbk.txt"
    path.write_bytes("这是GBK编码的中文".encode("gbk"))
    assert read_text(path) == "这是GBK编码的中文"


def test_read_utf8_bom_stripped(tmp_path):
    """Windows 记事本另存为 UTF-8 会带 BOM，不剥掉的话第一个字符是 \\ufeff。"""
    path = tmp_path / "bom.txt"
    path.write_bytes("\ufeff带BOM的文本".encode("utf-8-sig"))
    text = read_text(path)
    assert text == "带BOM的文本"
    assert not text.startswith("\ufeff")


def test_read_empty_file_raises(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with pytest.raises(ParseError, match="为空"):
        read_text(path)


def test_unsupported_suffix_raises(tmp_path):
    path = tmp_path / "a.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(ParseError, match="不支持解析"):
        parse_document(path)


def _minimal_pdf(text: str) -> bytes:
    """手工拼一个最小可解析 PDF（只含 ASCII 文本）。

    为什么不用 reportlab：为了测试一个 PDF 抽取函数去引一个生成库不划算，
    PDF 结构本身很简单（对象 + xref + trailer），手写一遍还顺便验证了自己真懂格式。
    """
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_parse_pdf_extracts_text(tmp_path):
    path = tmp_path / "hello.pdf"
    path.write_bytes(_minimal_pdf("Hello PDF Pipeline"))
    assert "Hello PDF Pipeline" in parse_document(path)


def test_parse_blank_pdf_raises(tmp_path):
    """纯图片/扫描件抽不出文本 → 必须失败，不能返回空串让管道以为成功。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as fh:
        writer.write(fh)

    with pytest.raises(ParseError, match="未抽取到文本"):
        parse_document(path)


def test_parse_corrupt_pdf_raises(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(ParseError):
        parse_document(path)
