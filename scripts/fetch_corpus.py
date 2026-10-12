"""拉取评测语料（无需 key）。语料**不进 git**，只落到本地目录，来源与筛选规则写在这里保证可复现。

两个来源：
- wiki ：中文维基百科指定分类下的条目（中文语料；查询=条目标题，衡量文档级召回）
- arxiv：arXiv 摘要（英文语料）

用法：
    python3 scripts/fetch_corpus.py --source wiki  --out /tmp/corpus_wiki  --per-category 30
    python3 scripts/fetch_corpus.py --source arxiv --out /tmp/corpus_arxiv --per-category 60
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

USER_AGENT = "rag-eval/0.1 (personal study project)"
ARXIV_API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_CATEGORIES = ["cs.CL", "cs.IR", "cs.AI", "cs.LG"]

WIKI_API = "https://zh.wikipedia.org/w/api.php"
WIKI_TOPICS = [
    "机器学习",
    "人工智能",
    "数据库",
    "计算机网络",
    "自然语言处理",
    "信息检索",
    "深度学习",
    "統計學",
    "大语言模型",
    "向量数据库",
    "知识图谱",
    "推荐系统",
    "卷积神经网络",
    "强化学习",
    "词嵌入",
    "语义搜索",
    "关系数据库",
    "数据库索引",
    "分布式计算",
    "微服务",
    "超文本传输协议",
    "传输控制协议",
    "操作系统",
    "算法",
    "数据结构",
    "计算机视觉",
    "语音识别",
    "概率论",
    "线性代数",
    "信息论",
    "快取",
    "虚拟化",
    "Python",
    "Java",
]
MIN_CHARS = 400  # 太短的条目（小作品）不适合做检索语料


def _get_json(url: str, retries: int = 4) -> dict:
    """带退避重试：公共 API 会 429（Too Many Requests），一次失败不该让整个语料抓取作废。"""
    delay = 5.0
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries:
                raise
            print(f"  429，{delay:.0f}s 后重试（第 {attempt + 1} 次）", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def fetch_wiki(topic: str, limit: int) -> list[dict]:
    """按主题关键词搜索条目，取**导言段**作为语料。

    两个 MediaWiki 坑（都踩过）：
    1. extracts 默认只返回 1 条；想一次拿多条必须配 exintro=1（官方限制：不开 exintro 时 exlimit 最大 1）。
    2. generator=categorymembers 在中文维基的分类里大多是子分类，过滤成 page 后剩不下几篇，
       所以这里改用 generator=search 按主题取。
    """
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": topic,
        "gsrlimit": str(limit),
        "gsrnamespace": "0",
        "prop": "extracts",
        "explaintext": "1",
        "exintro": "1",
        "exlimit": "max",
        "format": "json",
        "utf8": "1",
    }
    data = _get_json(f"{WIKI_API}?{urllib.parse.urlencode(params)}")
    pages = (data.get("query") or {}).get("pages") or {}
    entries = []
    for page in pages.values():
        text = (page.get("extract") or "").strip()
        title = page.get("title") or ""
        if title and len(text) >= MIN_CHARS:
            entries.append({"title": title, "body": text})
    return entries


def fetch_arxiv(category: str, count: int) -> list[dict]:
    params = {
        "search_query": f"cat:{category}",
        "start": 0,
        "max_results": count,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    request = urllib.request.Request(
        f"{ARXIV_API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    entries = []
    for entry in root.findall(f"{ATOM}entry"):
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
        if title and len(summary) >= 200:
            entries.append({"title": title, "body": summary})
    return entries


def safe_name(title: str, index: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", title).strip("-")[:60] or f"doc{index}"
    return f"{index:04d}_{slug}.txt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["wiki", "arxiv"], default="wiki")
    parser.add_argument("--out", default="/tmp/corpus_wiki")
    parser.add_argument("--per-category", type=int, default=30)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    categories = WIKI_TOPICS if args.source == "wiki" else ARXIV_CATEGORIES
    index = 0
    seen: set[str] = set()
    for category in categories:
        try:
            entries = (
                fetch_wiki(category, args.per_category)
                if args.source == "wiki"
                else fetch_arxiv(category, args.per_category)
            )
        except Exception as exc:  # 单个主题失败不影响整体语料
            print(f"{category}: 抓取失败 {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        added = 0
        for entry in entries:
            if entry["title"] in seen:
                continue
            seen.add(entry["title"])
            index += 1
            added += 1
            # 第一行固定是标题：评测时用标题当查询，衡量"标题能否召回自己的文档"
            (out_dir / safe_name(entry["title"], index)).write_text(
                f"{entry['title']}\n\n{entry['body']}\n", encoding="utf-8"
            )
        print(f"{category}: +{added}（累计 {index}）", file=sys.stderr)
        time.sleep(3.0)

    total_chars = sum(len(p.read_text(encoding="utf-8")) for p in out_dir.glob("*.txt"))
    print(f"完成：{index} 篇 -> {out_dir}（约 {total_chars} 字符）")


if __name__ == "__main__":
    main()
