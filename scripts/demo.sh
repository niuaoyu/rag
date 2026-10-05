#!/usr/bin/env bash
# 端到端 smoke demo：注册 -> 登录 -> 上传 -> 轮询 -> 普通问答 -> 工具问答
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
USER="demo_$(date +%s)"
PASS="demo123456"
DOC="${1:-samples/Java并发编程.txt}"

echo "== health =="
curl -s "$BASE/health"; echo

echo "== register =="
curl -s -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}"; echo

echo "== login =="
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

echo "== upload =="
DOC_ID=$(curl -s -X POST "$BASE/documents/upload" -H "$AUTH" -F "file=@$DOC" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["document_id"])')
echo "document_id=$DOC_ID"

echo "== poll status =="
for i in $(seq 1 30); do
  STATUS=$(curl -s "$BASE/documents/$DOC_ID" -H "$AUTH" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')
  echo "  status=$STATUS"
  [ "$STATUS" = "done" ] && break
  [ "$STATUS" = "failed" ] && { echo "ingest failed"; exit 1; }
  sleep 1
done

echo "== rag question =="
curl -s -X POST "$BASE/chat" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"volatile为什么不能保证i++线程安全？"}' | python3 -m json.tool

echo "== agent + tool question =="
curl -s -X POST "$BASE/chat" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"查询北京今天的天气，并结合我知识库中的跑步计划告诉我今天适不适合户外训练。"}' \
  | python3 -m json.tool

echo "== demo done =="
