"""拉取本地 ONNX 语义 embedding 模型（无需 API key）。

为什么自己下而不是让 fastembed 下：沙箱里 requests/httpx 无法用 MITM CA 校验（urllib 可以），
而且自己下能**校验 sha256**，模型来源与完整性都写死在脚本里，可复现。

用法：
    python3 scripts/fetch_embedding_model.py                 # 默认下载到 models/bge-small-zh-v1.5
    python3 scripts/fetch_embedding_model.py --out models/xxx --endpoint https://huggingface.co
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

REPO = "Qdrant/bge-small-zh-v1.5"
FILES = {
    "model_optimized.onnx": 94781076,
    "tokenizer.json": 439125,
    "tokenizer_config.json": 367,
    "special_tokens_map.json": 125,
    "config.json": 739,
}
# 官方 LFS oid：下载后校验，防止镜像返回坏文件却"看起来成功了"
EXPECTED_SHA256 = {
    "model_optimized.onnx": "1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38",
}


def download(base_url: str, name: str, dest: Path) -> str:
    url = f"{base_url.rstrip('/')}/{REPO}/resolve/main/{name}"
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as fh:
        while chunk := response.read(1024 * 1024):
            fh.write(chunk)
    return f"{name}: {dest.stat().st_size} bytes in {time.perf_counter() - started:.1f}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="models/bge-small-zh-v1.5")
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, expected_size in FILES.items():
        dest = out_dir / name
        if dest.exists() and dest.stat().st_size == expected_size and not args.force:
            print(f"{name}: 已存在，跳过")
            continue
        print(download(args.endpoint, name, dest))

    for name, expected_hash in EXPECTED_SHA256.items():
        digest = hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        if digest != expected_hash:
            print(f"!! {name} sha256 不匹配，模型可能损坏：{digest}", file=sys.stderr)
            raise SystemExit(1)
        print(f"{name}: sha256 校验通过")

    print(f"完成 -> {out_dir}")


if __name__ == "__main__":
    main()
