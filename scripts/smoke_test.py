"""独立 smoke test：对运行中的服务做一次最短端到端验证（不依赖 pytest）。"""
import io
import os
import sys
import time

import httpx

BASE = os.getenv("BASE", "http://localhost:8000")
DOC = os.getenv("DOC", "samples/Java并发编程.txt")


def main() -> int:
    # trust_env=False：避免本机 socks 代理干扰本地回环请求
    with httpx.Client(base_url=BASE, timeout=60, trust_env=False) as c:
        assert c.get("/health").json()["status"] == "ok"
        user = f"smoke_{int(time.time())}"
        c.post("/auth/register", json={"username": user, "password": "smoke12345"})
        token = c.post("/auth/login", json={"username": user, "password": "smoke12345"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        with open(DOC, "rb") as f:
            content = f.read()
        r = c.post("/documents/upload", headers=h,
                   files={"file": (os.path.basename(DOC), content, "text/plain")})
        print("upload:", r.status_code, r.json()["message"])
        doc_id = r.json()["document_id"]

        for _ in range(30):
            doc = c.get(f"/documents/{doc_id}", headers=h).json()
            if doc["status"] in ("done", "failed"):
                break
            time.sleep(1)
        print("ingest:", doc["status"], "chunks:", doc["chunk_count"])
        assert doc["status"] == "done"

        body = c.post("/chat", headers=h,
                      json={"question": "volatile为什么不能保证i++线程安全？"}).json()
        print("rag citations:", [(x["filename"], x["page"]) for x in body["citations"]])
        assert body["citations"], "expected citations"

        body = c.post("/chat", headers=h, json={
            "question": "查询北京今天的天气，并结合我知识库中的跑步计划告诉我今天适不适合户外训练。"
        }).json()
        print("tool calls:", body["tool_calls"])
        assert body["tool_calls"], "expected a tool call"
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
