"""检索质量评测：hit@k 与 MRR。

这是项目里**唯一**能产生"检索质量数字"的地方。规矩（写在 doc/架构与决策.md）：
- 只允许在 embedding_provider=openai（真语义模型）下产生的数字对外使用；
- provider=hash 时脚本会打印警告，此时数字只能证明"评测器跑得通"，不能当检索质量。

为什么用本地文件而不是打 HTTP：评测要能反复跑、要能对比参数（块大小/top-k/模型），
走 HTTP 会引入网络和后台任务的随机性，测出来的差异分不清是参数还是噪声。

用法：
    python3 scripts/eval_retrieval.py --corpus samples --top-k 3
    python3 scripts/eval_retrieval.py --corpus samples --chunk-size 200 --chunk-overlap 40
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.tokenizer import tokenizer_backend  # noqa: E402
from app.services.chunker import chunk_text  # noqa: E402
from app.services.embedding import build_embedder  # noqa: E402
from app.services.parser import parse_document  # noqa: E402

TEXT_SUFFIXES = {".txt", ".md"}


def load_corpus(corpus_dir: Path, chunk_size: int, chunk_overlap: int):
    chunks: list[dict] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = parse_document(path)
        for draft in chunk_text(text, size_tokens=chunk_size, overlap_tokens=chunk_overlap):
            chunks.append(
                {
                    "document": path.name,
                    "ordinal": draft.ordinal,
                    "text": draft.text,
                    "token_count": draft.token_count,
                }
            )
    return chunks


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def evaluate(corpus_dir: Path, queries_path: Path, top_k: int, chunk_size: int, overlap: int):
    chunks = load_corpus(corpus_dir, chunk_size, overlap)
    if not chunks:
        raise SystemExit(f"{corpus_dir} 下没有可评测的文本文件")
    queries = json.loads(queries_path.read_text(encoding="utf-8"))

    embedder = build_embedder(settings)
    if embedder.name == "hash":
        print("!! 警告：embedding_provider=hash，向量只有词面信息，下列数字**不是**语义检索质量。")
        print("!! 要用真实数字，请在 .env 里配置 EMBEDDING_PROVIDER=openai + key 后重跑。\n")

    started = time.perf_counter()
    chunk_vectors = _normalize(np.array(embedder.embed_documents([c["text"] for c in chunks])))
    embed_ms = int((time.perf_counter() - started) * 1000)

    rows = []
    reciprocal_ranks = []
    hits = 0
    for query in queries:
        vector = np.array(embedder.embed_query(query["question"]))
        norm = np.linalg.norm(vector)
        vector = vector / norm if norm else vector
        scores = chunk_vectors @ vector
        order = np.argsort(-scores)[:top_k]

        rank = None
        for position, index in enumerate(order, start=1):
            text = chunks[int(index)]["text"]
            if all(keyword in text for keyword in query["expected_keywords"]):
                rank = position
                break
        if rank:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

        rows.append(
            {
                "question": query["question"],
                "rank": rank,
                "top1": chunks[int(order[0])]["document"],
                "top1_score": round(float(scores[int(order[0])]), 4),
            }
        )

    total = len(queries)
    print(f"语料: {corpus_dir}  文档块数: {len(chunks)}  块大小: {chunk_size}±{overlap} token")
    print(f"embedding: {embedder.name}  dim={embedder.dim}  tokenizer: {tokenizer_backend()}")
    print(f"查询数: {total}  top_k: {top_k}  建向量耗时: {embed_ms}ms")
    print(f"块 token 数: min={min(c['token_count'] for c in chunks)} "
          f"median={int(statistics.median(c['token_count'] for c in chunks))} "
          f"max={max(c['token_count'] for c in chunks)}\n")

    for row in rows:
        mark = f"rank={row['rank']}" if row["rank"] else "MISS"
        print(f"  [{mark:8}] {row['question']}  → top1={row['top1']} ({row['top1_score']})")

    print(f"\nhit@{top_k} = {hits}/{total} = {hits / total:.2%}")
    print(f"MRR       = {sum(reciprocal_ranks) / total:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="samples")
    parser.add_argument("--queries", default="samples/eval_queries.json")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size_tokens)
    parser.add_argument("--chunk-overlap", type=int, default=settings.chunk_overlap_tokens)
    args = parser.parse_args()
    evaluate(
        Path(args.corpus), Path(args.queries), args.top_k, args.chunk_size, args.chunk_overlap
    )


if __name__ == "__main__":
    main()
