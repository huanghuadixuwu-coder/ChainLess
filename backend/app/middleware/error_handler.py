"""Unified error handling middleware for Chainless.

Maps common exceptions to a consistent error response format:

    {error: {code: str, message: str, detail: any | None}}

Registered in main.py during app construction.
"""

import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Mapping from exception types to user-facing error codes
ERROR_CODE_MAP: dict[type[Exception], str] = {
    ValueError: "VALIDATION_ERROR",
    TypeError: "VALIDATION_ERROR",
    KeyError: "VALIDATION_ERROR",
    PermissionError: "FORBIDDEN",
}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    detail: object = None,
) -> JSONResponse:
    """Build a JSON response with the standard envelope."""
    body: dict = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


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

        logger.error(
            "Unhandled %s: %s\n%s",
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )

        message = str(exc) if str(exc) else "An internal error occurred"
        detail = traceback.format_exc() if status_code == 500 else None
        return _error_response(status_code, error_code, message, detail)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle HTTPExceptions raised by route handlers or dependencies.

        If the exception detail is already a dict with an ``error`` key
        (e.g. from the auth endpoints), pass it through as-is.  Otherwise
        wrap it in the standard envelope.
        """
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )

        return _error_response(
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail) if exc.detail else "HTTP error occurred",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Handle Pydantic / FastAPI request validation errors (422)."""
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            detail=exc.errors(),
        )
