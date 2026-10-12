"""检索质量评测：文档级 recall@k 与 MRR。

这是项目里**唯一**能产生"检索质量数字"的地方。规矩（写在 doc/架构与决策.md）：
- `hash` 档的数字只能证明评测器跑得通，**不能当检索质量**（脚本会打印警告）；
- 对外使用的数字必须来自 `local`（本地 ONNX 语义模型）或 `openai` 档；
- 报告必须同时写清：语料来源、文档数、块参数、top_k。

两种查询来源：
1. `--queries FILE`：人工标注的关键词查询（chunk 级命中）。
2. `--auto-queries N`：从语料里采样 N 篇文档，用**标题**当查询，命中判据是"检索结果里出现该文档的块"
   （文档级召回）。不需要人工标注，可以复现、可以换语料重跑。

为什么在本地算而不是打 HTTP：评测要能反复跑、要能对比参数（模型/块大小/top-k），
走 HTTP 会引入后台任务与网络的随机性，测出来的差异分不清是参数还是噪声。

用法：
    python3 scripts/eval_retrieval.py --corpus /tmp/corpus_wiki --auto-queries 40 --provider local --top-k 5
    python3 scripts/eval_retrieval.py --corpus samples --queries samples/eval_queries.json --provider hash
"""

from __future__ import annotations

import argparse
import json
import random
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


def load_corpus(corpus_dir: Path, chunk_size: int, chunk_overlap: int) -> list[dict]:
    chunks: list[dict] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = parse_document(path)
        for draft in chunk_text(text, size_tokens=chunk_size, overlap_tokens=chunk_overlap):
            chunks.append(
                {
                    "document": path.name,
                    "title": text.splitlines()[0].strip() if text.splitlines() else path.stem,
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


def build_auto_queries(chunks: list[dict], count: int, seed: int = 42) -> list[dict]:
    """采样文档，用标题当查询。seed 固定 → 同样的语料每次得到同样的题，可比。"""
    by_doc: dict[str, dict] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk["document"], chunk)
    documents = sorted(by_doc)
    picked = random.Random(seed).sample(documents, min(count, len(documents)))
    return [
        {
            "question": by_doc[doc]["title"],
            "expected_documents": [doc],
            "origin": "auto-title",
        }
        for doc in picked
    ]



def evaluate(
    corpus_dir: Path,
    queries: list[dict],
    top_k: int,
    chunk_size: int,
    overlap: int,
    provider: str,
    report_path: Path | None = None,
) -> dict:
    chunks = load_corpus(corpus_dir, chunk_size, overlap)
    if not chunks:
        raise SystemExit(f"{corpus_dir} 下没有可评测的文本文件")

    settings.embedding_provider = provider
    embedder = build_embedder(settings)
    if embedder.name == "hash":
        print("!! 警告：provider=hash 只有词面信息，下列数字**不是**检索质量，只能证明评测器跑得通。")
        print("!! 要真实数字：--provider local（本地 ONNX 语义模型）或 --provider openai。\n")

    started = time.perf_counter()
    chunk_vectors = _normalize(np.array(embedder.embed_documents([c["text"] for c in chunks])))
    embed_ms = int((time.perf_counter() - started) * 1000)

    rows = []
    reciprocal_ranks: list[float] = []
    doc_hits = 0
    doc_total = 0
    keyword_hits = 0
    keyword_total = 0
    for query in queries:
        vector = np.array(embedder.embed_query(query["question"]))
        norm = np.linalg.norm(vector)
        vector = vector / norm if norm else vector
        scores = chunk_vectors @ vector
        order = np.argsort(-scores)[:top_k]

        rank = None
        if query.get("expected_documents"):
            doc_total += 1
            for position, index in enumerate(order, start=1):
                if chunks[int(index)]["document"] in query["expected_documents"]:
                    rank = position
                    break
            if rank:
                doc_hits += 1
        elif query.get("expected_keywords"):
            keyword_total += 1
            for position, index in enumerate(order, start=1):
                text = chunks[int(index)]["text"]
                if all(word in text for word in query["expected_keywords"]):
                    rank = position
                    break
            if rank:
                keyword_hits += 1

        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        rows.append(
            {
                "question": query["question"],
                "origin": query.get("origin", "manual"),
                "rank": rank,
                "top1_document": chunks[int(order[0])]["document"],
                "top1_score": round(float(scores[int(order[0])]), 4),
            }
        )

    total = len(queries)
    token_counts = [c["token_count"] for c in chunks]
    summary = {
        "provider": embedder.name,
        "dim": embedder.dim,
        "corpus": str(corpus_dir),
        "documents": len({c["document"] for c in chunks}),
        "chunks": len(chunks),
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "top_k": top_k,
        "queries": total,
        "doc_recall_at_k": round(doc_hits / doc_total, 4) if doc_total else None,
        "doc_queries": doc_total,
        "keyword_hit_at_k": round(keyword_hits / keyword_total, 4) if keyword_total else None,
        "mrr": round(sum(reciprocal_ranks) / total, 4),
        "embed_ms": embed_ms,
        "tokenizer": tokenizer_backend(),
        "chunk_tokens": {
            "min": min(token_counts),
            "median": int(statistics.median(token_counts)),
            "max": max(token_counts),
        },
        "rows": rows,
    }

    print(f"语料: {summary['corpus']}  文档 {summary['documents']} 篇  块 {summary['chunks']} 个")
    print(
        f"embedding: {summary['provider']} dim={summary['dim']}  tokenizer: {summary['tokenizer']}"
        f"  块 token: min={summary['chunk_tokens']['min']} "
        f"median={summary['chunk_tokens']['median']} max={summary['chunk_tokens']['max']}"
    )
    print(
        f"查询 {total} 条  top_k={top_k}  建向量 {embed_ms}ms"
        f"（{embed_ms / max(summary['chunks'], 1):.2f} ms/块）\n"
    )
    misses = [row for row in rows if not row["rank"]]
    for row in rows[:5]:
        mark = f"rank={row['rank']}" if row["rank"] else "MISS"
        print(f"  [{mark:8}] {row['question'][:40]} → {row['top1_document'][:40]}")
    if len(rows) > 5:
        print(f"  ...（共 {len(rows)} 条，完整结果见报告 JSON）")
    if misses:
        print(f"\n  未命中 {len(misses)} 条：")
        for row in misses[:10]:
            print(f"    - {row['question'][:50]} → top1={row['top1_document'][:40]}")
    if doc_total:
        print(
            f"\ndoc recall@{top_k} = {doc_hits}/{doc_total} "
            f"= {summary['doc_recall_at_k']:.2%}（文档级：检索结果里是否出现该文档的块）"
        )
    if keyword_total:
        print(
            f"keyword hit@{top_k} = {keyword_hits}/{keyword_total} "
            f"= {summary['keyword_hit_at_k']:.2%}"
        )
    print(f"MRR@{top_k}        = {summary['mrr']:.4f}")

    if report_path:
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入 {report_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="samples")
    parser.add_argument("--queries", default=None, help="人工标注的查询 JSON")
    parser.add_argument("--auto-queries", type=int, default=0, help="自动生成多少条标题查询")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size_tokens)
    parser.add_argument("--chunk-overlap", type=int, default=settings.chunk_overlap_tokens)
    parser.add_argument("--provider", default=settings.embedding_provider)
    parser.add_argument("--report", default=None, help="把结果写成 JSON（留档用）")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if args.auto_queries:
        chunks = load_corpus(corpus_dir, args.chunk_size, args.chunk_overlap)
        queries = build_auto_queries(chunks, args.auto_queries)
    elif args.queries:
        queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    else:
        raise SystemExit("必须给 --queries 或 --auto-queries")

    evaluate(
        corpus_dir,
        queries,
        args.top_k,
        args.chunk_size,
        args.chunk_overlap,
        args.provider,
        Path(args.report) if args.report else None,
    )


if __name__ == "__main__":
    main()
