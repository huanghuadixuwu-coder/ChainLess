from starlette.requests import Request

from app.middleware.rate_limit import RateLimitMiddleware
from app.services.auth_service import create_access_token


def _request(
    authorization: str | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    request_headers = list(headers or [])
    if authorization is not None:
        request_headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/settings",
            "headers": request_headers,
            "client": ("203.0.113.10", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_rate_limit_identity_uses_authenticated_tenant_user() -> None:
    token = create_access_token(
        tenant_id="tenant-a",
        user_id="user-a",
        username="admin",
    )

    identity = RateLimitMiddleware._get_rate_limit_identity(
        _request(f"Bearer {token}")
    )

    assert identity == "user:tenant-a:user-a"


def test_rate_limit_identity_falls_back_to_ip_without_valid_token() -> None:
    assert (
        RateLimitMiddleware._get_rate_limit_identity(_request())
        == "ip:203.0.113.10"
    )
    assert (
        RateLimitMiddleware._get_rate_limit_identity(_request("Bearer invalid"))
        == "ip:203.0.113.10"
    )


def test_ip_identity_prefers_trusted_real_ip_over_spoofed_xff() -> None:
    request = _request(
        headers=[
            (b"x-real-ip", b"198.51.100.9"),
            (b"x-forwarded-for", b"1.2.3.4, 198.51.100.9"),
        ]
    )

    assert RateLimitMiddleware._get_rate_limit_identity(request) == "ip:198.51.100.9"
