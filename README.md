# RAG 知识库问答 Agent

上传文档 → 解析切块 → 向量入库 → 检索 → LLM 带引用回答。
技术栈：FastAPI + SQLAlchemy + Qdrant + tiktoken，LLM/Embedding 走 OpenAI 兼容 HTTP 接口。

## 60 秒跑起来（本地，不依赖外网）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 改掉 JWT_SECRET；不配 LLM key 也能跑（见下）
python3 scripts/upgrade_db.py   # 已有 app.db 时补 M4 新增列
uvicorn app.main:app --reload
```

```bash
# 另开一个终端：注册 → 上传 → 轮询 → 看切块 → 提问（带来源引用）
python3 scripts/e2e_demo.py
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 健康检查。**额外暴露** tokenizer / embedding_provider / llm_configured，用来一眼看出当前是真 embedding 还是 hash、LLM 有没有配 |
| POST | `/api/v1/users/register` `/login` | 注册 / 登录（JWT） |
| GET | `/api/v1/users/me` | 当前用户 |
| POST | `/api/v1/documents` | 上传（201 立即返回，解析在后台） |
| GET | `/api/v1/documents` | 列表（**不返回正文**，避免响应体过大） |
| GET | `/api/v1/documents/{id}` | 详情（轮询用：done 时 text 非空，failed 时 error_message 非空） |
| GET | `/api/v1/documents/{id}/chunks` | 切块结果（块序号 / 字符数 / token 数） |
| POST | `/api/v1/documents/{id}/reprocess` | 幂等重跑处理管道 |
| POST | `/api/v1/chat/ask` | 检索 + 生成，返回带来源引用的答案 |
| POST | `/api/v1/chat/ask/stream` | 同上，SSE 流式（先推 citations，再推增量） |

## 三种回答模式（防止自欺的关键设计）

`/chat/ask` 的 `mode` 字段只有三种值，任何情况下都不会伪造答案：

| mode | 含义 |
| --- | --- |
| `llm` | 真的调了模型 |
| `retrieval_only` | 没配 key 或模型报错 → 只返回检索结果 |
| `no_context` | 没检索到相关内容 → 不调模型 |

## 配置开关

| 变量 | 作用 |
| --- | --- |
| `EMBEDDING_PROVIDER` | `hash`（离线、只有词面信息，仅用于本地/CI）/ `openai`（真语义模型） |
| `QDRANT_URL` | 空 → 嵌入式模式（单进程）；填 → 走 Qdrant 服务端（生产） |
| `LLM_API_KEY` | 空 → `retrieval_only` |
| `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS` | 切块参数，单位是 token（tiktoken cl100k_base） |

## 测试与评测

```bash
python3 -m pytest tests -q --ignore=tests/debug   # 82 passed
python3 scripts/eval_retrieval.py --corpus samples --top-k 3   # hit@k / MRR
```

> `eval_retrieval.py` 在 `EMBEDDING_PROVIDER=hash` 下会打印警告：此时的 hit@k **不是**语义检索质量。
> 对外使用的检索数字必须在 `openai` 档下产生。

## 部署

```bash
cp .env.example .env   # 填 JWT_SECRET / EMBEDDING_* / LLM_*
docker compose up -d   # api + qdrant 服务端
```

文档索引见 `doc/`：`m1..m4` 是已交付模块的接口契约，`m5..m8` 是本次新增，
`架构与决策.md` 记录设计取舍与实测数字，`m12拷打清单.md` 是面试拷打题，`简历素材.md` 是可辩护的简历措辞。
