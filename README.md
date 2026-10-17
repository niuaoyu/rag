# RAG 知识库问答 Agent

上传文档 → RAG 检索 → LLM 问答并附原文溯源。技术栈：FastAPI + SQLAlchemy + Qdrant。

## Agent 问答层

- `POST /api/v1/agent/ask`：有限步工具编排（工具注册表 + 步数预算 + 超时 + 降级），每次运行写一份 JSONL 轨迹到 `AGENT_TRACE_DIR`。
- 模型接入：OpenAI 兼容接口，配置 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 即可；未配置时接口返回 503。
- 本地验证：`python3 -m pytest -q`

## 求职材料流水线

`skills/agent-resume-packaging/`：把仓库里的真实交付物变成可核验的简历要点（主张—证据账本 + 反假审计脚本）。用法见 `doc/agent问答层与简历包装.md`。

