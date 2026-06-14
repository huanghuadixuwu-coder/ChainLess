"""Authenticated encryption and redacted metadata for stored secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "channel_config",
    "cookie",
    "password",
    "secret",
    "secret_key",
    "token",
    "webhook_url",
}


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return normalized in SENSITIVE_KEYS or normalized.endswith(
        ("_api_key", "_password", "_secret", "_token", "_webhook_url")
    )


class SecretDecryptionError(ValueError):
    """Raised without including secret material when ciphertext is invalid."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(
        b"chainless/settings-secret-encryption/v1\0"
        + settings.secret_encryption_key.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("Secret value cannot be blank")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise SecretDecryptionError("Stored secret could not be decrypted") from exc


def secret_metadata(value: str | None) -> dict[str, str | bool | None]:
    """Return stable, non-reversible metadata suitable for API responses."""
    if not value:
        return {"configured": False, "mask": None, "fingerprint": None}
    fingerprint = hmac.new(
        settings.secret_encryption_key.encode("utf-8"),
        b"chainless/secret-mask/v1\0" + value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]
    return {
        "configured": True,
        "mask": "********",
        "fingerprint": fingerprint,
    }


def redact_sensitive_data(value: Any, *, sensitive: bool = False) -> Any:
    """Recursively redact known secret-bearing values for errors and audits."""
    if sensitive:
        return "[redacted]"
    if isinstance(value, dict):
        location = value.get("loc")
        location_is_sensitive = isinstance(location, (list, tuple)) and any(
            is_sensitive_key(part) for part in location
        )
        return {
            key: redact_sensitive_data(
                item,
                sensitive=location_is_sensitive or is_sensitive_key(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_data(item) for item in value]
    return value


def safe_error_message(exc: BaseException, operation: str = "Operation") -> str:
    """Return an error message that cannot contain runtime secret material."""
    return f"{operation} failed ({type(exc).__name__})"
