
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False,  # APP_NAME 和 app_name 都能匹配
        extra="ignore",        # 忽略 .env 里多余的变量

        )
    app_name: str = "RAG"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./app.db"

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30

    upload_dir: Path = Path("uploads")

    # ---- M5 切块 ----
    # 单位是 token（tiktoken cl100k_base），不是字符。char 兜底见 app/core/tokenizer.py
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 60
    chunk_min_chars: int = 30          # 解析结果短于此值视为空文档 → failed

    # ---- M6 向量入库 ----
    # embedding_provider: hash（离线确定性，仅用于测试/CI，不具备语义）| openai（OpenAI 兼容 /embeddings）
    embedding_provider: str = "hash"
    embedding_base_url: str = "https://llm.ujn.edu.cn/v1"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"
    embedding_dim: int = 256           # hash 提供方必须显式给维度；openai 提供方以接口返回为准
    qdrant_path: str = "./qdrant_data" # 本地嵌入式模式（单进程独占文件锁）
    qdrant_url: str = ""               # 非空则走远程 Qdrant（生产/Docker）
    qdrant_collection: str = "chunks"

    # ---- M7 检索 ----
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.0   # 低于此相似度的命中直接丢弃

    # ---- M8 问答 ----
    llm_base_url: str = "https://llm.ujn.edu.cn/v1"
    llm_api_key: str = ""             # 空 → /chat/ask 只返回检索结果（mode=retrieval_only），不伪造答案
    llm_model: str = "glm-4-flash"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 60.0

    # 启动时是否立刻建表/建 collection（测试里关掉更快）
    auto_init_storage: bool = True


settings = Settings()