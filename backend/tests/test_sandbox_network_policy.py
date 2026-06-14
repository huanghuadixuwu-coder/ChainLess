"""Sandbox network and AppArmor policy tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_policy():
    path = Path("/repo/sandbox-proxy/policy.py")
    spec = importlib.util.spec_from_file_location("sandbox_proxy_policy", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_network_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _load_policy()
    monkeypatch.delenv("SANDBOX_NETWORK_MODE", raising=False)
    monkeypatch.delenv("SANDBOX_NETWORK_WHITELIST", raising=False)
    assert policy.configured_network_mode() == "none"


def test_non_none_network_requires_explicit_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _load_policy()
    monkeypatch.setenv("SANDBOX_NETWORK_MODE", "sandbox-egress")
    monkeypatch.setenv("SANDBOX_NETWORK_WHITELIST", "approved-egress")
    with pytest.raises(RuntimeError, match="not in SANDBOX_NETWORK_WHITELIST"):
        policy.configured_network_mode()

    monkeypatch.setenv("SANDBOX_NETWORK_WHITELIST", "approved-egress,sandbox-egress")
    assert policy.configured_network_mode() == "sandbox-egress"


def test_apparmor_is_opt_in_without_weakening_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _load_policy()
    monkeypatch.delenv("SANDBOX_APPARMOR_PROFILE", raising=False)
    assert policy.configured_security_options() == ["no-new-privileges:true"]

    monkeypatch.setenv("SANDBOX_APPARMOR_PROFILE", "chainless-sandbox")
    assert policy.configured_security_options() == [
        "no-new-privileges:true",
        "apparmor=chainless-sandbox",
    ]
