"""Production gateway, compose boundary, and fail-closed tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from app.config import Settings, validate_production_settings

ROOT = Path("/repo")


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_production_publishes_only_nginx_and_debug_ports_are_localhost_only() -> None:
    production = _compose("docker-compose.yml")["services"]
    assert production["nginx"]["container_name"] == "chainless-nginx"
    assert production["nginx"]["ports"] == ["80:80"]
    for service in ("db", "redis", "sandbox-proxy", "backend", "frontend"):
        assert "ports" not in production[service]

    debug = _compose("docker-compose.debug.yml")["services"]
    for service in ("db", "redis", "sandbox-proxy", "backend", "frontend"):
        assert all(str(port).startswith("127.0.0.1:") for port in debug[service]["ports"])


def test_private_networks_and_docker_socket_boundary() -> None:
    compose = _compose("docker-compose.yml")
    services = compose["services"]
    assert compose["networks"]["app"]["internal"] is True
    assert compose["networks"]["data"]["internal"] is True
    assert compose["networks"]["sandbox_net"]["internal"] is True
    assert compose["networks"]["egress"] is None
    assert services["sandbox"]["network_mode"] == "none"
    assert "ports" not in services["sandbox-proxy"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in services["sandbox-proxy"]["volumes"]
    assert all(
        "/var/run/docker.sock" not in str(services[name].get("volumes", []))
        for name in ("backend", "worker", "sandbox")
    )
    assert "egress" in services["backend"]["networks"]
    assert "egress" in services["worker"]["networks"]
    assert all(
        "egress" not in services[name].get("networks", [])
        for name in ("db", "redis", "sandbox-proxy", "frontend")
    )


def test_sandbox_proxy_readiness_is_health_gated_and_bounded() -> None:
    production = _compose("docker-compose.yml")["services"]
    test = _compose("docker-compose.test.yml")["services"]

    for proxy in (production["sandbox-proxy"], test["sandbox-proxy-test"]):
        healthcheck = proxy["healthcheck"]
        command = " ".join(healthcheck["test"])
        assert "python" in command
        assert "http://127.0.0.1:9001/health" in command
        assert healthcheck["timeout"]
        assert healthcheck["retries"] > 0

    assert production["backend"]["depends_on"]["sandbox-proxy"]["condition"] == "service_healthy"
    assert production["worker"]["depends_on"]["sandbox-proxy"]["condition"] == "service_healthy"


def test_backend_healthchecks_use_public_liveness_endpoint() -> None:
    production = _compose("docker-compose.yml")["services"]
    test = _compose("docker-compose.test.yml")["services"]

    for service in (production["backend"], test["backend-test-server"]):
        command = " ".join(service["healthcheck"]["test"])
        assert "/api/v1/health" in command
        assert "/api/v1/system/health" not in command


def test_artifact_storage_is_managed_volume_with_bounded_defaults() -> None:
    production = _compose("docker-compose.yml")
    test = _compose("docker-compose.test.yml")["services"]
    services = production["services"]

    assert "artifact_data" in production["volumes"]
    for service_name in ("backend", "worker"):
        service = services[service_name]
        assert "artifact_data:/data/artifacts" in service["volumes"]
        assert service["environment"]["ARTIFACT_BASE_PATH"] == "/data/artifacts"
        assert service["environment"]["ARTIFACT_MAX_FILE_BYTES"] == "${ARTIFACT_MAX_FILE_BYTES:-200000}"
        assert service["environment"]["ARTIFACT_MAX_DIFF_BYTES"] == "${ARTIFACT_MAX_DIFF_BYTES:-100000}"
        assert service["environment"]["ARTIFACT_TENANT_QUOTA_BYTES"] == "${ARTIFACT_TENANT_QUOTA_BYTES:-50000000}"
        assert service["environment"]["ARTIFACT_RETENTION_DAYS"] == "${ARTIFACT_RETENTION_DAYS:-30}"

    assert test["backend-test"]["environment"]["ARTIFACT_BASE_PATH"] == "/tmp/chainless-test-artifacts"


def test_production_boundary_probe_covers_w5_auth_boundary() -> None:
    probe = (ROOT / "backend/scripts/production_boundary_probe.py").read_text(
        encoding="utf-8"
    )

    assert "w5-boundary-probe-" in probe
    assert '"/api/v1/health"' in probe
    assert '"/api/v1/system/health"' in probe
    assert '"/api/v1/system/metrics"' in probe
    assert '"/api/v1/memories/"' in probe
    assert '"member_memory"' in probe
    assert '"admin_health"' in probe
    assert "conversation-and-temp-tenant-deleted" in probe


def test_live_docker_tests_are_isolated_behind_a_healthy_proxy_dependency() -> None:
    services = _compose("docker-compose.test.yml")["services"]
    isolated = services["backend-test"]
    live = services["backend-test-live"]
    proxy = services["sandbox-proxy-test"]

    assert "CHAINLESS_LIVE_DOCKER" not in isolated["environment"]
    assert "sandbox-proxy-test" not in isolated.get("depends_on", {})
    assert "live-docker" not in isolated.get("profiles", [])
    assert isolated["environment"]["SANDBOX_PROXY_URL"] == "http://127.0.0.1:9001"

    assert live["environment"]["CHAINLESS_LIVE_DOCKER"] == "1"
    assert live["environment"]["SANDBOX_PROXY_URL"] == "http://sandbox-proxy-test:9001"
    assert live["depends_on"]["sandbox-proxy-test"]["condition"] == "service_healthy"
    assert "live-docker" in live["profiles"]
    assert "live-docker" in proxy["profiles"]
    assert services["backend-test-server"]["environment"]["SANDBOX_PROXY_URL"] == "http://127.0.0.1:9001"


def test_http_config_has_no_tls_cert_dependency_and_tls_is_opt_in() -> None:
    production_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    tls_text = (ROOT / "docker-compose.tls.yml").read_text(encoding="utf-8")
    nginx_http = (ROOT / "nginx/conf.d/chainless.conf").read_text(encoding="utf-8")
    assert "fullchain.pem" not in production_text
    assert "privkey.pem" not in production_text
    assert "ssl_certificate" not in nginx_http
    assert "chainless-tls.conf" in tls_text
    assert "./nginx/certs" in tls_text


def test_nginx_routes_same_origin_and_preserves_sse() -> None:
    nginx = (ROOT / "nginx/conf.d/chainless.conf").read_text(encoding="utf-8")
    frontend_api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    assert "resolver 127.0.0.11 valid=10s ipv6=off" in nginx
    assert "set $chainless_frontend http://frontend:3000" in nginx
    assert "set $chainless_backend http://backend:8000" in nginx
    assert "location /api/v1/" in nginx
    assert "proxy_pass $chainless_backend" in nginx
    assert "proxy_pass $chainless_frontend" in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_read_timeout 3600s" in nginx
    assert "window.location.origin" in frontend_api
    assert 'url.port = "8000"' not in frontend_api


@pytest.mark.parametrize(
    "field,value",
    [
        ("secret_key", "dev-secret-key-change-in-production"),
        ("secret_encryption_key", ""),
        ("proxy_auth_token", "dev-token"),
        ("bootstrap_admin_password", "admin123"),
        ("database_url", "postgresql+asyncpg://chainless:chainless_dev@db:5432/chainless"),
    ],
)
def test_production_configuration_fails_closed(field: str, value: str) -> None:
    values = {
        "app_env": "production",
        "secret_key": "safe-secret-key",
        "secret_encryption_key": "safe-encryption-key",
        "proxy_auth_token": "safe-proxy-token",
        "bootstrap_admin_password": "safe-admin-password",
        "database_url": "postgresql+asyncpg://chainless:safe-password@db:5432/chainless",
    }
    values[field] = value
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_production_settings(Settings(**values))


def test_production_configuration_accepts_non_placeholder_secrets() -> None:
    validate_production_settings(
        Settings(
            app_env="production",
            secret_key="safe-secret-key",
            secret_encryption_key="safe-encryption-key",
            proxy_auth_token="safe-proxy-token",
            bootstrap_admin_password="safe-admin-password",
            database_url="postgresql+asyncpg://chainless:safe-password@db:5432/chainless",
        )
    )


def test_slice2_security_defaults_are_fixed_and_bounded() -> None:
    config = Settings(_env_file=None)

    assert 0 < config.subagent_max_connections_per_run <= config.subagent_max_connections_global
    assert config.subagent_max_connections_global <= 64
    assert 0 < config.subagent_read_timeout_seconds <= 5
    assert 0 < config.subagent_handler_timeout_seconds <= 60
    assert 0 < config.subagent_cancellation_grace_seconds <= 5
    assert 0 < config.disposable_parent_max_concurrency <= 5
    assert 0 < config.disposable_parent_max_stdout_bytes <= config.disposable_parent_max_output_bytes
    assert 0 < config.disposable_parent_max_stderr_bytes <= config.disposable_parent_max_output_bytes


def test_rate_limit_default_supports_full_settings_console_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    config = Settings(_env_file=None)
    production = _compose("docker-compose.yml")["services"]

    assert config.rate_limit_enabled is True
    assert 300 <= config.rate_limit_per_minute <= 1000
    assert production["backend"]["environment"]["RATE_LIMIT_PER_MINUTE"] == "${RATE_LIMIT_PER_MINUTE:-300}"


@pytest.mark.asyncio
async def test_application_security_headers_are_set(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
