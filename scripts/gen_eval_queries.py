"""用 LLM 生成"改写查询"评测集：故意避开原文档的表面词，专门用来暴露词面检索的弱点。

为什么需要它：用文档标题当查询时，标题往往**原样出现在正文里**，
词面哈希向量（hash）也能拿高分 —— 这种基准分不出"语义检索"和"字符串匹配"。
改写查询要求：换一种说法、不得出现标题里的实词，但仍只能由该文档回答。

产物是标准 queries JSON（带 expected_documents），可直接喂给 scripts/eval_retrieval.py。

用法：
    python3 scripts/gen_eval_queries.py --corpus /tmp/corpus_wiki --count 20 --out /tmp/queries_paraphrase.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.llm import build_llm  # noqa: E402

SYSTEM = (
    "你在为一个中文检索评测集出题。"
    "用户会给你一篇百科条目的标题和正文。"
    "你要写一个**改写式问题**：意思与正文相关，但**不得出现标题里的任何实词**（虚词可以）。"
    "问题必须能且只能由这篇正文回答，长度 10~30 字，只输出问题本身，不要解释、不要引号。"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    files = sorted(Path(args.corpus).glob("*.txt"))
    if not files:
        raise SystemExit(f"{args.corpus} 下没有 txt")
    picked = random.Random(args.seed).sample(files, min(args.count, len(files)))

    llm = build_llm(settings)
    queries = []
    for index, path in enumerate(picked, start=1):
        text = path.read_text(encoding="utf-8")
        title, _, body = text.partition("\n\n")
        user = f"标题：{title.strip()}\n\n正文：{body.strip()[:1200]}"
        try:
            question = llm.complete(SYSTEM, user).strip().strip("“”\"'").splitlines()[0]
        except Exception as exc:  # 单条失败不影响整体
            print(f"[{index}] 生成失败 {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        queries.append(
            {
                "question": question,
                "expected_documents": [path.name],
                "origin": "llm-paraphrase",
                "source_title": title.strip(),
            }
        )
        print(f"[{index}/{len(picked)}] {title.strip()[:20]} -> {question}")

    Path(args.out).write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {len(queries)} 条 -> {args.out}")


if __name__ == "__main__":
    main()
