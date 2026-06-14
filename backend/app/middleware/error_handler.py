"""Unified error handling middleware for Chainless.

Maps common exceptions to a consistent error response format:

    {error: {code: str, message: str, detail: any | None}}

Registered in main.py during app construction.
"""

import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.contracts import (
    default_error_code,
    error_response,
    normalize_http_detail,
)
from app.core.secrets import redact_sensitive_data, safe_error_message

logger = logging.getLogger(__name__)

# Mapping from exception types to user-facing error codes
ERROR_CODE_MAP: dict[type[Exception], str] = {
    ValueError: "VALIDATION_ERROR",
    TypeError: "VALIDATION_ERROR",
    KeyError: "VALIDATION_ERROR",
    PermissionError: "FORBIDDEN",
}


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app.

    Order matters: FastAPI checks handlers in reverse registration order,
    so the catch-all ``Exception`` handler is registered first, then more
    specific handlers are registered on top.
    """

    @app.exception_handler(Exception)
    async def catch_all_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle any exception not caught by a more specific handler."""
        error_code = ERROR_CODE_MAP.get(type(exc), "INTERNAL_ERROR")
        status_code = 400 if error_code == "VALIDATION_ERROR" else 500

        logger.exception("Unhandled exception type: %s", type(exc).__name__)

        message = safe_error_message(exc)
        if status_code == 500:
            message = "Internal server error"
            detail = None
        else:
            detail = None
        return error_response(status_code, error_code, message, detail)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle HTTPExceptions raised by route handlers or dependencies.

        Normalize all HTTP exceptions into the canonical error contract.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content=redact_sensitive_data(normalize_http_detail(exc.status_code, exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Handle Pydantic / FastAPI request validation errors (422)."""
        return error_response(
            status_code=422,
            code=default_error_code(422),
            message="Request validation failed",
            detail=redact_sensitive_data(exc.errors()),
        )
