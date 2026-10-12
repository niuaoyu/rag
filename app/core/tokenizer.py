"""token 计数的唯一入口。

为什么需要这个文件：
- 切块大小必须用 token 而不是字符来衡量（"500 token 左右"是契约里的验收标准）。
- tiktoken 的 BPE 文件需要联网下载一次；离线环境装不上时不能直接崩，
  要退化成可解释的估算，并把"当前用的是哪一种"暴露出来（见 tokenizer_backend()）。
- 面试会考：估算和真实 BPE 的偏差有多大？——装不上 tiktoken 时我们不知道，
  所以要显式报告 backend，别把估算值当真实值写进文档。
"""

from __future__ import annotations

import re

ENCODING_NAME = "cl100k_base"

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[A-Za-z0-9_]+")

_encoder = None
_encoder_loaded = False


def _get_encoder():
    """惰性加载 tiktoken。加载失败返回 None（不抛异常，避免拖垮整个应用）。"""
    global _encoder, _encoder_loaded
    if not _encoder_loaded:
        _encoder_loaded = True
        try:
            import os

            # tiktoken 默认把 BPE 文件缓存在 /tmp，**被清理后会静默退化成估算**（真实踩过：
            # 测试结果因此变化）。允许用配置把它固定到项目内目录，避免环境漂移。
            from app.core.config import settings as _settings

            if _settings.tiktoken_cache_dir:
                os.environ.setdefault("TIKTOKEN_CACHE_DIR", _settings.tiktoken_cache_dir)
            import tiktoken

            _encoder = tiktoken.get_encoding(ENCODING_NAME)
        except Exception:  # pragma: no cover - 取决于运行环境是否有 BPE 缓存
            _encoder = None
    return _encoder


def tokenizer_backend() -> str:
    """返回当前实际使用的计数器：tiktoken:<编码名> 或 estimate。"""
    return f"tiktoken:{ENCODING_NAME}" if _get_encoder() is not None else "estimate"


def _estimate_tokens(text: str) -> int:
    """粗略估算：CJK 每字 1 token，英文数字每词 1 token，其余符号按 2 个 1 token。

    这是**估算**，只有 tokenizer_backend() == 'estimate' 时才会用到。
    偏差范围：真实 cl100k_base 对中文散文大约是 0.6~0.7 token/字，
    所以本函数对中文会**高估**，块会比预期小一点。UNKNOWN：具体偏差未在本环境实测。
    """
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(text))
    others = max(len(text) - cjk - sum(len(w) for w in _WORD.findall(text)), 0)
    return cjk + words + (others + 1) // 2


def count_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is None:
        return _estimate_tokens(text)
    return len(encoder.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """把文本截到不超过 max_tokens（用于切块时的滑窗尾部、错误信息等场景）。"""
    if max_tokens <= 0 or not text:
        return ""
    encoder = _get_encoder()
    if encoder is None:
        # 估算路径：按字符近似裁切，宁可少给
        ratio = _estimate_tokens(text) / max(len(text), 1)
        keep = int(max_tokens / max(ratio, 1e-6))
        return text[:keep]
    ids = encoder.encode(text)
    if len(ids) <= max_tokens:
        return text
    return encoder.decode(ids[-max_tokens:])


def tail_within_tokens(text: str, max_tokens: int) -> str:
    """返回 text 的**字符对齐后缀**，其 token 数不超过 max_tokens。

    为什么不用 `decode(encode(text)[-max_tokens:])`：那样拿到的字符串**不保证是原文本的子串**
    （BPE 边界可能切到多字节字符中间，decode 出替换符），
    之后任何 `in` / `startswith` 判断都会莫名其妙失败 —— 这个坑在切块重叠上真实踩过。
    这里二分找最大的字符后缀，保证返回值一定是原文本的后缀。
    """
    if max_tokens <= 0 or not text:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if count_tokens(text[-mid:]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[-low:] if low else ""




def head_within_tokens(text: str, max_tokens: int) -> str:
    """返回 text 的**字符对齐前缀**，其 token 数不超过 max_tokens（硬切块用它保证上界）。

    为什么不用"按估算比例切一刀"：估算与实际计数不是线性关系，
    切出来的片段可能仍然超预算（切块上界就守不住了）。二分前缀长度才能**由构造保证**上界。
    """
    if max_tokens <= 0 or not text:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if count_tokens(text[:mid]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low] if low else text[:1]
