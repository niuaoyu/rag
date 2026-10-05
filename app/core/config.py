"""全部运行时配置都从环境变量 / .env 读取，代码里不允许出现魔法值。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 应用
    app_name: str = "RAG MVP"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # 数据库
    database_url: str = "sqlite:///./app.db"

    # JWT
    jwt_secret: str = "dev-only-secret-please-change-in-production-32chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # 上传
    upload_dir: str = "uploads"
    max_upload_mb: int = 20

    # 检索
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 4

    # Embedding
    embedding_provider: str = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_dim: int = 256

    # LLM
    llm_provider: str = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.2

    # Weather tool
    weather_api_key: str = ""
    weather_base_url: str = "https://api.openweathermap.org/data/2.5"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
