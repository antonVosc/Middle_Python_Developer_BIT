from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://docflow:docflow@localhost:5432/docflow"
    redis_url: str = "redis://localhost:6379/0"
    llm_api_key: str = ""
    llm_model: str = "deepseek/deepseek-chat-v3-0324:free"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_rpm_limit: int = 15
    external_api_base_url: str = "https://hr-api.bit-company.ru"
    external_api_key: str = ""
    upload_dir: str = "/app/uploads"


settings = Settings()
