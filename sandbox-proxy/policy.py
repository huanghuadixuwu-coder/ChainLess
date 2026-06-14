"""Pure sandbox policy helpers, kept separate for deterministic tests."""

from __future__ import annotations

import os


def configured_network_mode() -> str:
    """Return an allowed network mode, defaulting to fully disabled networking."""
    requested = os.environ.get("SANDBOX_NETWORK_MODE", "none").strip() or "none"
    if requested == "none":
        return requested

    whitelist = {
        item.strip()
        for item in os.environ.get("SANDBOX_NETWORK_WHITELIST", "").split(",")
        if item.strip()
    }
    if requested not in whitelist:
        raise RuntimeError(
            f"SANDBOX_NETWORK_MODE={requested!r} is not in SANDBOX_NETWORK_WHITELIST"
        )
    return requested


def configured_security_options() -> list[str]:
    """Return mandatory and optional Docker security options."""
    options = ["no-new-privileges:true"]
    apparmor_profile = os.environ.get("SANDBOX_APPARMOR_PROFILE", "").strip()
    if apparmor_profile:
        options.append(f"apparmor={apparmor_profile}")
    return options
