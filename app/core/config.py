
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

    # agent 问答层：步数预算、工具超时、轨迹目录和模型接入配置
    agent_max_steps: int = 6
    agent_tool_timeout_seconds: float = 5.0
    agent_trace_dir: Path = Path("traces")
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

settings = Settings()