"""HTTP 相关的公共小工具。

为什么需要它：httpx 默认用 certifi 的 CA 包，**不读** SSL_CERT_FILE/REQUESTS_CA_BUNDLE。
在企业内网、校园网自签 CA、或带 TLS 中间代理的环境里，这会导致所有出网请求
`CERTIFICATE_VERIFY_FAILED`（本项目的沙箱就是这种情况，真跑 e2e 时才暴露）。

处理方式：显式尊重环境里的 CA 配置，而不是图省事写 verify=False —— 后者等于关掉 TLS 校验。
"""

from __future__ import annotations

import os
from pathlib import Path

CA_ENV_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")


def resolve_verify() -> bool | str:
    """返回 httpx 的 verify 参数：环境里给了可用的 CA 文件就用它，否则用默认（True）。"""
    for name in CA_ENV_VARS:
        value = os.environ.get(name)
        if value and Path(value).is_file():
            return value
    return True
