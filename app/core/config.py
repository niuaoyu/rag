
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

settings = Settings()