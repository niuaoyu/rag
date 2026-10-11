"""tokenizer 单测：计数为正、截断不超限、后端可观测。

注意：tiktoken 的 BPE 文件需要联网下载一次；离线环境会退化成估算。
所以这里**不断言具体数值**（数值依赖后端），只断言"性质"和"后端名可读"。
"""

from app.core.tokenizer import count_tokens, tokenizer_backend, truncate_to_tokens


def test_backend_name_is_reported():
    assert tokenizer_backend() in {"tiktoken:cl100k_base", "estimate"}


def test_counts_are_positive_and_monotonic():
    assert count_tokens("") == 0
    short = count_tokens("你好")
    long = count_tokens("你好" * 100)
    assert short > 0
    assert long > short


def test_truncate_respects_budget():
    text = "检索增强生成" * 200
    truncated = truncate_to_tokens(text, 20)
    assert count_tokens(truncated) <= 20
    assert truncated  # 不能截成空串


def test_truncate_returns_original_when_short():
    assert truncate_to_tokens("短文本", 100) == "短文本"
