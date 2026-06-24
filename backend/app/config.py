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
    secret_encryption_key: str = "dev-secret-encryption-key-change-in-production"
    bootstrap_admin_password: str = "admin123"

    # Sandbox proxy
    proxy_auth_token: str = "dev-token"
    sandbox_proxy_url: str = "http://sandbox-proxy:9001"
    subagent_control_root: str = "/run/chainless-control"
    subagent_control_gid: int = 10001
    subagent_capability_ttl_seconds: float = 30.0
    subagent_max_connections_per_run: int = 8
    subagent_max_connections_global: int = 32
    subagent_read_timeout_seconds: float = 2.0
    subagent_handler_timeout_seconds: float = 30.0
    subagent_cancellation_grace_seconds: float = 1.0
    disposable_parent_max_concurrency: int = 5
    disposable_parent_max_stdout_bytes: int = 262144
    disposable_parent_max_stderr_bytes: int = 262144
    disposable_parent_max_output_bytes: int = 524288

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
    rate_limit_per_minute: int = 300

    # Memory
    memory_base_path: str = "/data/memory"
    memory_injection_budget_chars: int = 4000
    memory_embedding_model: str = "embedding-3"
    short_term_context_ttl_seconds: int = 3600

    # Artifacts
    artifact_base_path: str = "/data/artifacts"
    artifact_max_file_bytes: int = 200_000
    artifact_max_diff_bytes: int = 100_000
    artifact_tenant_quota_bytes: int = 50_000_000
    artifact_retention_days: int = 30
    artifact_preview_allowed_origins: str = (
        "http://localhost,http://localhost:3000,"
        "http://127.0.0.1,http://127.0.0.1:3000"
    )

    # Capability acquisition
    acquisition_enabled: bool = True
    acquisition_code_as_action_enabled: bool = True
    acquisition_api_runtime_enabled: bool = True
    acquisition_browser_runtime_enabled: bool = True
    acquisition_mcp_runtime_enabled: bool = True
    acquisition_workspace_connectors_enabled: bool = True

    # Debug
    debug: bool = False
    app_env: str = "development"
    cors_allowed_origins: str = "http://localhost,http://127.0.0.1"


def validate_production_settings(config: Settings) -> None:
    """Fail closed when production is configured with placeholder secrets."""
    if config.app_env.lower() != "production":
        return

    unsafe_values = {
        "secret_key": {
            "",
            "dev-secret-key-change-in-production",
            "change-me",
            "change-me-to-a-random-secret",
        },
        "secret_encryption_key": {
            "",
            "dev-secret-encryption-key-change-in-production",
            "change-me",
            "change-me-to-a-random-secret",
        },
        "proxy_auth_token": {
            "",
            "dev-token",
            "change-me",
            "change-me-to-a-random-token",
        },
        "bootstrap_admin_password": {
            "",
            "admin123",
            "change-me",
            "change-me-to-a-random-password",
        },
    }
    for field, rejected in unsafe_values.items():
        value = getattr(config, field)
        if value in rejected:
            raise RuntimeError(f"Unsafe production configuration: {field} is not set")

    if "chainless_dev" in config.database_url or "change-me" in config.database_url:
        raise RuntimeError("Unsafe production configuration: database password is not set")


settings = Settings()
