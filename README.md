# RAG Agent MVP

一个**可运行、可演示**的个人知识库 Agent 后端：

> 上传个人文档 → 自动建立知识库 → 对话式问答并带**来源引用** → 需要时调用**外部工具**完成简单任务。

这是「先看到完整产品，再决定学什么」的第一阶段产物。默认配置下**完全离线可跑**（哈希向量 + mock LLM + mock 天气），
不需要任何 API Key 就能完整演示整条链路；配置 API Key 后即可切换到真实的大模型与 Embedding。

---

## 1. 能力清单

| 模块 | 实现 |
|---|---|
| 用户系统 | 注册 / 登录 / JWT 鉴权（`Authorization: Bearer <token>`） |
| 文档上传 | `POST /documents/upload`，限制类型与大小 |
| 文档解析 | PDF（含**页码**）/ TXT / Markdown |
| 异步处理 | 上传即返回 `202`，FastAPI BackgroundTasks 后台解析，状态 `pending → processing → done/failed` |
| 切块 | 按字符滑窗 + 段落/句子边界，保留页码 |
| Embedding | 抽象层，`hash`（离线默认） / `openai`（任意 OpenAI 兼容接口） |
| 向量库 | 向量存 SQLite，进程内余弦相似度检索（可替换为 pgvector/Qdrant/Chroma） |
| 语义检索 | `GET /chat` 前自动检索 Top-K 相关 chunk |
| LLM 回答 | 抽象层，`mock`（离线默认） / `openai` 兼容接口 |
| Citation | 回答附 `filename + page + 原文片段 + score` |
| Conversation | 会话与消息落库，支持多轮上下文 |
| Agent Tool Calling | 至少一个真实工具 `get_weather`，模型自行判断是否调用；可 `use_tools=false` 关闭 |
| 日志 | 控制台 + `logs/app.log`（轮转） |
| 测试 | pytest 关键路径 14 个用例 |
| Docker | `Dockerfile` + `docker-compose.yml`，一键启动 |
| Demo | `scripts/demo.sh` 与 `scripts/smoke_test.py` 端到端验证 |

---

## 2. 快速开始（Docker，推荐）

```bash
cd /home/nay/final/rag
docker compose up -d --build

# 验证
curl http://localhost:8000/health
# {"status":"ok","app":"RAG MVP","version":"0.1.0"}
```

打开交互式文档：**http://localhost:8000/docs**

停止 / 清理：

```bash
docker compose down          # 停止
docker compose down -v       # 停止并删除数据卷
```

---

## 3. 本地运行（开发）

```bash
cd /home/nay/final/rag

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # 默认全离线，可直接用
uvicorn app.main:app --reload --port 8000
```

或使用 Makefile：

```bash
make install
make run
make test
```

---

## 4. 一次完整演示（对应第一阶段验收标准）

### 方式 A：一行脚本

```bash
# 先用一个 TXT/PDF 作为知识库文件
make run                       # 另开一个终端启动服务
python scripts/smoke_test.py   # 自动跑完注册→上传→检索→工具调用
```

### 方式 B：手动 curl

```bash
BASE=http://localhost:8000

# 1) 注册
curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo123456"}'

# 2) 登录，拿到 token
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo123456"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

# 3) 上传文档
curl -s -X POST $BASE/documents/upload -H "$AUTH" \
  -F "file=@/path/to/Java并发编程.pdf"
# {"document_id":1,"filename":"Java并发编程.pdf","status":"pending","message":"文件已上传，正在处理。"}

# 4) 轮询处理状态，直到 done
curl -s $BASE/documents/1 -H "$AUTH"

# 5) RAG 问答（带引用）
curl -s -X POST $BASE/chat -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"volatile为什么不能保证i++线程安全？"}'

# 6) Agent + 工具调用
curl -s -X POST $BASE/chat -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"查询北京今天的天气，并结合我知识库中的跑步计划告诉我今天适不适合户外训练。"}'
```

预期结果：

- 上传后返回 `"文件已上传，正在处理。"`；
- 状态轮询变为 `done`，`chunk_count > 0`；
- RAG 问答返回答案，并在 `citations` 中给出 `filename / page / content / score`；
- 工具问答的 `tool_calls` 中出现 `get_weather`，`result` 是天气数据，回答综合了天气与知识库内容。

---

## 5. API 一览

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| GET | `/health` | 健康检查 | 否 |
| POST | `/auth/register` | 注册 | 否 |
| POST | `/auth/login` | 登录，返回 JWT | 否 |
| GET | `/auth/me` | 当前用户 | 是 |
| POST | `/documents/upload` | 上传文档（PDF/TXT/MD） | 是 |
| GET | `/documents` | 文档列表 | 是 |
| GET | `/documents/{id}` | 文档详情/状态 | 是 |
| DELETE | `/documents/{id}` | 删除文档 | 是 |
| POST | `/chat` | 提问（RAG + Agent） | 是 |
| GET | `/chat/conversations` | 会话列表 | 是 |
| GET | `/chat/conversations/{id}/messages` | 会话消息 | 是 |

`POST /chat` 请求体：

```json
{
  "question": "volatile为什么不能保证i++线程安全？",
  "conversation_id": null,
  "use_tools": true
}
```

响应体：

```json
{
  "conversation_id": 1,
  "answer": "...",
  "citations": [
    {"document_id": 1, "filename": "Java并发编程.pdf", "page": 132, "content": "...", "score": 0.71}
  ],
  "tool_calls": [
    {"name": "get_weather", "arguments": {"city": "北京"}, "result": {"temperature_c": 18.0}, "ok": true}
  ]
}
```

---

## 6. 切换到真实模型 / 真实天气

编辑 `.env`，把 provider 从 `mock/hash` 换成真实实现即可，**代码无需改动**：

```dotenv
# 真实 LLM（OpenAI / DeepSeek / Qwen / 本地 vLLM 等任意 OpenAI 兼容接口）
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-xxxx

# 真实 Embedding
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=sk-xxxx

# 真实天气（不填则用离线 mock）
WEATHER_API_KEY=your-openweathermap-key
```

Docker 下通过环境变量注入：

```bash
LLM_PROVIDER=openai LLM_API_KEY=sk-xxx docker compose up -d
```

---

## 7. 测试

```bash
make test
# 或
pytest -q
```

测试覆盖：健康检查、注册/登录/JWT、重复用户名、错误密码、未授权访问、文档上传与异步入库、
不支持类型拒绝、跨用户文档隔离、RAG 引用、多轮会话、Agent 工具调用、工具开关、Embedding 相似度。

---

## 8. 目录结构

```text
app/
  main.py                 FastAPI 入口与路由注册
  api/
    deps.py               JWT 依赖，解析当前用户
    auth.py               注册/登录/me
    documents.py          上传/列表/详情/删除
    chat.py               问答/会话
  core/
    config.py             全部配置（.env）
    security.py           bcrypt + JWT
    logging.py            统一日志
  db/
    session.py            engine / session / init_db
    models.py             User / Document / Chunk / Conversation / Message
  schemas/                Pydantic 请求响应模型
  services/
    parsing.py            PDF/TXT 解析
    chunking.py           切块
    embedding.py          向量化抽象
    vectorstore.py        余弦检索
    ingest.py             解析→切块→embedding→落库 后台流水线
    llm.py                LLM 抽象（mock/openai）
    rag.py                RAG + Agent 主流程
    tools/weather.py      天气工具 + function calling schema
tests/                    pytest 关键路径测试
scripts/
  demo.sh                 curl 版端到端演示
  smoke_test.py           Python 版端到端验证
Dockerfile / docker-compose.yml / Makefile / .env.example
```

---

## 9. 设计取舍（面试可讲点）

- **为什么 Embedding / LLM 都做抽象层？** 让默认离线可跑、可测试，同时一行配置切换真实供应商，避免 demo 被 API Key 卡住。
- **为什么向量先放 SQLite 做暴力检索？** MVP 阶段数据量小，避免引入额外基础设施；检索接口已隔离，替换成 pgvector/Qdrant 不影响上层。
- **为什么用 BackgroundTasks 而不是 Celery/Kafka？** 第一阶段只验证完整链路，不引入未经市场验证的复杂度；接口语义（`202 + 状态轮询`）保留了未来换分布式任务系统的空间。
- **Citation 如何保证可信？** 引用直接来自检索命中的 chunk 元数据（文件名 + 页码），不依赖模型自己编造来源。
- **Agent 如何不失控？** 只暴露白名单工具 schema；工具参数由模型产出后仍需服务端解析执行，并把结果作为 `tool` 消息回填再做二次生成。

---

## 10. 当前阶段的边界

已完成第一阶段最小可用产品。按原计划，**接下来不是继续加功能，而是从招聘视角倒推**：
哪些部分值得写进简历、面试官会怎么拷打、哪些能力需要真正变成自己的，然后再进入撤 AI 重写与深耕。
