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
    # 推理型网关（如 DeepSeek-R 系）需要显式设置 effort，否则输出可能全进思考通道、content 为空。
    # 空字符串 = 不向网关传递该参数（兼容 OpenAI 非推理模型）。
    llm_reasoning_effort: str = ""
    # 0 = 不传 max_tokens。注意：推理模型给小 max_tokens 会把预算耗在思考上导致 content 截断。
    llm_max_tokens: int = 0
    llm_timeout: int = 90

    # Agent 工具调用轮次上限（防止模型反复 tool_call 不收敛）
    tool_max_rounds: int = 3

    # Weather tool
    weather_api_key: str = ""
    weather_base_url: str = "https://api.openweathermap.org/data/2.5"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
