"""一键端到端演示：注册 → 登录 → 上传 → 轮询状态 → 看切块 → 提问（带来源引用）。

用法：
    # 终端 1
    uvicorn app.main:app --reload
    # 终端 2
    python3 scripts/e2e_demo.py                 # 默认 http://127.0.0.1:8000
    python3 scripts/e2e_demo.py --base http://127.0.0.1:8000 --file samples/rag_notes.txt

它同时是一份"实测记录器"：把每个环节的耗时、块数、token 数、检索得分打出来，
这些数字是简历和面试唯一允许使用的数字（不许手写）。
"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

import httpx

DEFAULT_FILES = ["samples/rag_notes.txt", "samples/agent_notes.txt"]
POLL_INTERVAL = 0.2
POLL_TIMEOUT = 30.0


def _step(title: str) -> None:
    print(f"\n=== {title} ===")


def register_and_login(client: httpx.Client, base: str) -> tuple[str, str]:
    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"
    response = client.post(
        f"{base}/api/v1/users/register", json={"email": email, "password": password}
    )
    response.raise_for_status()
    response = client.post(
        f"{base}/api/v1/users/login", json={"email": email, "password": password}
    )
    response.raise_for_status()
    return email, response.json()["access_token"]


def upload(client: httpx.Client, base: str, token: str, path: Path) -> dict:
    started = time.perf_counter()
    with path.open("rb") as fh:
        response = client.post(
            f"{base}/api/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (path.name, fh, "text/plain")},
        )
    response.raise_for_status()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = response.json()
    body["upload_ms"] = elapsed_ms
    return body


def wait_done(client: httpx.Client, base: str, token: str, doc_id: int) -> tuple[dict, int]:
    started = time.perf_counter()
    while time.perf_counter() - started < POLL_TIMEOUT:
        response = client.get(
            f"{base}/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        body = response.json()
        if body["status"] in {"done", "failed"}:
            return body, int((time.perf_counter() - started) * 1000)
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"文档 {doc_id} 在 {POLL_TIMEOUT}s 内没有进入终态")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    parser.add_argument("--question", default="RAG 的检索阶段主要解决什么问题？")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    with httpx.Client(timeout=60.0) as client:
        _step("0. /healthz（当前跑的是真 embedding 还是 hash、token 计数的后端、LLM 有没有配）")
        health = client.get(f"{base}/healthz").json()
        for key, value in health.items():
            print(f"  {key}: {value}")

        _step("1. 注册 + 登录")
        email, token = register_and_login(client, base)
        print(f"  用户: {email}")

        documents = []
        for raw in args.files:
            path = Path(raw)
            if not path.exists():
                print(f"  跳过（文件不存在）: {path}")
                continue
            _step(f"2. 上传 {path.name}（应当立即返回 201，不等解析）")
            body = upload(client, base, token, path)
            print(f"  响应 status={body['status']}（后台任务还没跑完）upload_ms={body['upload_ms']}")
            detail, waited_ms = wait_done(client, base, token, body["id"])
            print(
                f"  轮询 {waited_ms}ms 后: status={detail['status']} "
                f"chars={detail['char_count']} tokens={detail['token_count']}"
            )
            if detail["status"] == "failed":
                print(f"  失败原因: {detail['error_message']}")
                continue

            chunks = client.get(
                f"{base}/api/v1/documents/{detail['id']}/chunks",
                headers={"Authorization": f"Bearer {token}"},
            ).json()
            sizes = [chunk["token_count"] for chunk in chunks]
            print(
                f"  切块: {len(chunks)} 块, token 数 min/avg/max = "
                f"{min(sizes)}/{sum(sizes) // len(sizes)}/{max(sizes)}"
            )
            documents.append(detail["id"])

        _step("3. 提问（mode=llm 才是真模型回答；retrieval_only 表示没配 key）")
        started = time.perf_counter()
        response = client.post(
            f"{base}/api/v1/chat/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": args.question, "top_k": 3},
        )
        if response.status_code != 200 or "application/json" not in response.headers.get(
            "content-type", ""
        ):
            raise SystemExit(
                f"提问失败：http={response.status_code} "
                f"content-type={response.headers.get('content-type')} body={response.text[:300]}"
            )
        answer = response.json()
        wall_ms = int((time.perf_counter() - started) * 1000)
        print(f"  question: {answer['question']}")
        print(f"  mode: {answer['mode']}  retrieved={answer['retrieved_count']}  "
              f"服务端 latency_ms={answer['latency_ms']}  客户端 wall_ms={wall_ms}")
        print(f"  answer: {answer['answer']}")
        if answer.get("note"):
            print(f"  note: {answer['note']}")
        for citation in answer["citations"]:
            print(
                f"  [{citation['index']}] {citation['filename']} 第{citation['ordinal'] + 1}块 "
                f"score={citation['score']} :: {citation['snippet'][:40]}..."
            )


if __name__ == "__main__":
    main()
