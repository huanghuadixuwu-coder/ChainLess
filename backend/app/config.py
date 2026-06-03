from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://chainless:chainless_dev@db:5432/chainless"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    secret_key: str = "dev-secret-key-change-in-production"

    # LLM
    glm_api_key: str = ""
    default_llm_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    default_llm_model: str = "glm-4.5-air"
    embedding_model: str = "text-embedding-3-small"

    # Sandbox proxy
    proxy_auth_token: str = "dev-token"
    sandbox_proxy_url: str = "http://sandbox-proxy:9001"

    # Sandbox pool
    sandbox_image: str = "chainless_sandbox:latest"
    sandbox_pool_min: int = 2
    sandbox_pool_max: int = 10
    sandbox_timeout_seconds: int = 30
    sandbox_memory_mb: int = 512

    # Auth tokens
    access_token_expire_minutes: int = 60

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60


settings = Settings()
