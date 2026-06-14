"""Canonical API response and error contracts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


ErrorDetail = dict[str, Any] | list[Any] | str | int | float | bool | None


def error_envelope(
    code: str,
    message: str,
    detail: ErrorDetail = None,
) -> dict[str, dict[str, Any]]:
    """Return the canonical JSON error envelope."""
    error: dict[str, Any] = {"code": code, "message": message, "detail": detail}
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    detail: ErrorDetail = None,
) -> JSONResponse:
    """Build a FastAPI JSONResponse using the canonical error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(code, message, detail),
    )


def api_error(
    status_code: int,
    code: str,
    message: str,
    detail: ErrorDetail = None,
) -> HTTPException:
    """Build an HTTPException whose detail is already canonical."""
    return HTTPException(
        status_code=status_code,
        detail=error_envelope(code, message, detail),
    )


def validation_error(message: str, detail: ErrorDetail = None) -> HTTPException:
    return api_error(422, "VALIDATION_ERROR", message, detail)


def not_found(code: str, message: str) -> HTTPException:
    return api_error(status.HTTP_404_NOT_FOUND, code, message)


def auth_error(message: str = "Invalid credentials") -> HTTPException:
    return api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_FAILED", message)


def auth_expired(message: str = "Invalid or expired token") -> HTTPException:
    return api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_EXPIRED", message)


def normalize_http_detail(status_code: int, detail: Any) -> dict[str, dict[str, Any]]:
    """Normalize arbitrary HTTPException detail into the canonical envelope."""
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        error = detail["error"]
        return error_envelope(
            str(error.get("code") or default_error_code(status_code)),
            str(error.get("message") or default_error_message(status_code)),
            error.get("detail"),
        )
    return error_envelope(
        default_error_code(status_code),
        str(detail) if detail else default_error_message(status_code),
    )


def default_error_code(status_code: int) -> str:
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "AUTH_EXPIRED"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "FORBIDDEN"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "NOT_FOUND"
    if status_code == status.HTTP_409_CONFLICT:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "HTTP_ERROR"


def default_error_message(status_code: int) -> str:
    return {
        status.HTTP_401_UNAUTHORIZED: "Authentication required",
        status.HTTP_403_FORBIDDEN: "Forbidden",
        status.HTTP_404_NOT_FOUND: "Resource not found",
        status.HTTP_409_CONFLICT: "Conflict",
        422: "Request validation failed",
    }.get(status_code, "HTTP error occurred")
