"""Sandbox — isolated code execution via Docker containers managed by sandbox-proxy."""

from app.core.sandbox.manager import SandboxManager, get_sandbox_manager

__all__ = ["SandboxManager", "get_sandbox_manager"]
