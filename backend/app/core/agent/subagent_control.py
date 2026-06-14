"""Backend-owned capability and RPC boundary for sandbox sub-agent spawning."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_ALLOWED_METHOD = "spawn_sub_agent"
_ALLOWED_REQUEST_KEYS = {"capability", "method", "params"}
_ALLOWED_PARAMS = {"prompt", "context"}
_MAX_REQUEST_BYTES = 64 * 1024


def _is_safe_run_id(run_id: object) -> bool:
    return (
        isinstance(run_id, str)
        and run_id not in {".", ".."}
        and _SAFE_RUN_ID.fullmatch(run_id) is not None
    )


class CapabilityError(RuntimeError):
    """Raised when a control capability cannot be issued."""


@dataclass(frozen=True)
class _Capability:
    tenant_id: str
    parent_run_id: str
    operation: str
    expires_at: float


SpawnHandler = Callable[..., object | Awaitable[object]]


class CapabilityAuthority:
    """The sole owner of sub-agent permissions and run-scoped UDS RPC."""

    def __init__(
        self,
        handler: SpawnHandler,
        *,
        control_root: str | Path = "/run/chainless-control",
        control_gid: int = 10001,
        clock: Callable[[], float] = time.monotonic,
        max_connections_per_run: int = 8,
        max_connections_global: int = 32,
        read_timeout_seconds: float = 2.0,
        handler_timeout_seconds: float = 30.0,
        cancellation_grace_seconds: float = 1.0,
    ) -> None:
        if not 0 < max_connections_per_run <= max_connections_global:
            raise ValueError("invalid connection limits")
        if min(read_timeout_seconds, handler_timeout_seconds, cancellation_grace_seconds) <= 0:
            raise ValueError("timeouts must be positive")
        self._handler = handler
        self._control_root = Path(control_root)
        self._control_gid = control_gid
        self._clock = clock
        self._max_connections_per_run = max_connections_per_run
        self._max_connections_global = max_connections_global
        self._read_timeout_seconds = read_timeout_seconds
        self._handler_timeout_seconds = handler_timeout_seconds
        self._cancellation_grace_seconds = cancellation_grace_seconds
        self._active_parents: set[tuple[str, str]] = set()
        self._capabilities: dict[str, _Capability] = {}
        self._connections_by_parent: dict[tuple[str, str], int] = {}
        self._active_connections = 0
        self._handlers_by_parent: dict[
            tuple[str, str],
            set[asyncio.Future[object]],
        ] = {}
        self._clients_by_parent: dict[tuple[str, str], set[asyncio.Task]] = {}
        self._reapers_by_parent: dict[tuple[str, str], asyncio.Task] = {}
        self._close_lock = asyncio.Lock()
        self._closed = False

    @property
    def active_connection_count(self) -> int:
        return self._active_connections

    @property
    def inflight_handler_count(self) -> int:
        return sum(len(tasks) for tasks in self._handlers_by_parent.values())

    @property
    def reaper_count(self) -> int:
        return len(self._reapers_by_parent)

    async def aclose(self) -> None:
        """Close only after every tracked handler and reaper has terminated."""
        async with self._close_lock:
            if self._closed:
                return
            for parent in set(self._handlers_by_parent):
                await self._cancel_handlers(parent)
            reapers = set(self._reapers_by_parent.values())
            if reapers:
                await asyncio.wait(
                    reapers,
                    timeout=self._cancellation_grace_seconds,
                )
            for parent, task in list(self._reapers_by_parent.items()):
                if task.done():
                    self._reapers_by_parent.pop(parent, None)
            for parent, tasks in list(self._handlers_by_parent.items()):
                for task in set(tasks):
                    if task.done():
                        self._discard_handler(parent, task)
                if self._handlers_by_parent.get(parent):
                    self._ensure_reaper(parent)
            if self.inflight_handler_count or self.reaper_count:
                raise RuntimeError(
                    "authority close incomplete: "
                    f"handlers={self.inflight_handler_count}, "
                    f"reapers={self.reaper_count}"
                )
            self._active_parents.clear()
            self._capabilities.clear()
            self._closed = True

    def activate_parent(self, tenant_id: str, parent_run_id: str) -> None:
        self._require_open()
        self._validate_scope(tenant_id, parent_run_id)
        self._active_parents.add((tenant_id, parent_run_id))

    def issue_capability(
        self,
        tenant_id: str,
        parent_run_id: str,
        *,
        ttl_seconds: float = 30.0,
    ) -> str:
        self._require_open()
        self._validate_scope(tenant_id, parent_run_id)
        if ttl_seconds <= 0:
            raise CapabilityError("capability ttl must be positive")
        if (tenant_id, parent_run_id) not in self._active_parents:
            raise CapabilityError("parent run is not active")
        token = secrets.token_urlsafe(32)
        self._capabilities[token] = _Capability(
            tenant_id=tenant_id,
            parent_run_id=parent_run_id,
            operation=_ALLOWED_METHOD,
            expires_at=self._clock() + ttl_seconds,
        )
        return token

    async def revoke_parent(self, tenant_id: str, parent_run_id: str) -> None:
        parent = (tenant_id, parent_run_id)
        self._active_parents.discard(parent)
        self._capabilities = {
            token: capability
            for token, capability in self._capabilities.items()
            if (capability.tenant_id, capability.parent_run_id)
            != parent
        }
        await self._cancel_handlers(parent)

    @asynccontextmanager
    async def serve_run(
        self,
        tenant_id: str,
        parent_run_id: str,
    ) -> AsyncIterator[Path]:
        self._require_open()
        self._validate_scope(tenant_id, parent_run_id)
        if (tenant_id, parent_run_id) not in self._active_parents:
            raise CapabilityError("parent run is not active")
        run_dir = self._control_root / parent_run_id
        socket_path = run_dir / "subagent.sock"
        server: asyncio.AbstractServer | None = None
        try:
            run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chown(run_dir, -1, self._control_gid)
            os.chmod(run_dir, 0o710)
            socket_path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(
                lambda reader, writer: self._handle_client(
                    reader,
                    writer,
                    tenant_id=tenant_id,
                    parent_run_id=parent_run_id,
                ),
                path=str(socket_path),
            )
            os.chown(socket_path, -1, self._control_gid)
            os.chmod(socket_path, 0o660)
            yield socket_path
        finally:
            await self._await_authoritative_cleanup(
                self._cleanup_run(
                    tenant_id,
                    parent_run_id,
                    server=server,
                    socket_path=socket_path,
                    run_dir=run_dir,
                )
            )

    async def _cleanup_run(
        self,
        tenant_id: str,
        parent_run_id: str,
        *,
        server: asyncio.AbstractServer | None,
        socket_path: Path,
        run_dir: Path,
    ) -> None:
        parent = (tenant_id, parent_run_id)
        try:
            await self.revoke_parent(tenant_id, parent_run_id)
        finally:
            try:
                if server is not None:
                    server.close()
                    await server.wait_closed()
            finally:
                try:
                    await self._drain_clients(parent)
                finally:
                    try:
                        socket_path.unlink(missing_ok=True)
                    finally:
                        run_dir.rmdir()

    @staticmethod
    async def _await_authoritative_cleanup(cleanup: Awaitable[None]) -> None:
        cleanup_task = asyncio.create_task(cleanup)
        cancelled = False
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancelled = True
        cleanup_task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        tenant_id: str,
        parent_run_id: str,
    ) -> None:
        parent = (tenant_id, parent_run_id)
        client_task = asyncio.current_task()
        if client_task is not None:
            self._clients_by_parent.setdefault(parent, set()).add(client_task)
        if not self._reserve_connection(parent):
            try:
                await self._write_response(
                    writer,
                    {"ok": False, "error": "connection limit exceeded"},
                )
            finally:
                self._discard_client(parent, client_task)
            return
        response: dict[str, object]
        try:
            raw = await asyncio.wait_for(
                reader.readline(),
                timeout=self._read_timeout_seconds,
            )
            if not raw or len(raw) > _MAX_REQUEST_BYTES:
                raise ValueError("request rejected")
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request rejected")
            if set(request) != _ALLOWED_REQUEST_KEYS:
                raise ValueError("request rejected")
            method = request.get("method")
            params = request.get("params")
            if (
                method != _ALLOWED_METHOD
                or not isinstance(params, dict)
                or set(params) - _ALLOWED_PARAMS
                or not isinstance(params.get("prompt"), str)
                or not isinstance(params.get("context", ""), str)
            ):
                raise ValueError("request rejected")
            capability = self._authorize(
                request.get("capability"),
                tenant_id=tenant_id,
                parent_run_id=parent_run_id,
                operation=method,
            )
            result = await self._run_handler(
                capability,
                params["prompt"],
                params.get("context", ""),
            )
            response = {"ok": True, "result": result}
        except asyncio.TimeoutError:
            response = {"ok": False, "error": "request timeout"}
        except asyncio.CancelledError:
            response = {"ok": False, "error": "spawn cancelled"}
        except ValueError:
            response = {"ok": False, "error": "request rejected"}
        except CapabilityError:
            response = {"ok": False, "error": "capability rejected"}
        except RuntimeError as exc:
            response = {
                "ok": False,
                "error": "spawn timeout" if str(exc) == "spawn timeout" else "spawn failed",
            }
        except Exception:
            response = {"ok": False, "error": "spawn failed"}
        finally:
            self._release_connection(parent)
        try:
            await self._write_response(writer, response)
        finally:
            self._discard_client(parent, client_task)

    async def _run_handler(
        self,
        capability: _Capability,
        prompt: str,
        context: str,
    ) -> object:
        result = self._handler(
            prompt,
            context,
            tenant_id=capability.tenant_id,
            parent_run_id=capability.parent_run_id,
            depth=1,
        )
        if not inspect.isawaitable(result):
            return result
        task = asyncio.ensure_future(result)
        parent = (capability.tenant_id, capability.parent_run_id)
        self._handlers_by_parent.setdefault(parent, set()).add(task)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self._handler_timeout_seconds,
            )
            if parent not in self._active_parents:
                raise asyncio.CancelledError
            return result
        except asyncio.TimeoutError:
            await self._cancel_tasks({task})
            if not task.done():
                self._ensure_reaper(parent)
            raise RuntimeError("spawn timeout")
        finally:
            if task.done():
                self._discard_handler(parent, task)
            else:
                self._ensure_reaper(parent)

    async def _cancel_handlers(self, parent: tuple[str, str]) -> None:
        tasks_snapshot = set(self._handlers_by_parent.get(parent, set()))
        await self._cancel_tasks(tasks_snapshot)
        tasks = self._handlers_by_parent.get(parent)
        if tasks is None:
            return
        for task in tasks_snapshot:
            if task.done():
                self._discard_handler(parent, task)
        if self._handlers_by_parent.get(parent):
            self._ensure_reaper(parent)

    def _ensure_reaper(self, parent: tuple[str, str]) -> None:
        current = self._reapers_by_parent.get(parent)
        if current is not None and not current.done():
            return
        self._reapers_by_parent[parent] = asyncio.create_task(self._reap_handlers(parent))

    async def _reap_handlers(self, parent: tuple[str, str]) -> None:
        reaper_task = asyncio.current_task()
        try:
            while tasks := self._handlers_by_parent.get(parent):
                for task in set(tasks):
                    if task.done():
                        self._discard_handler(parent, task)
                    else:
                        task.cancel()
                if self._handlers_by_parent.get(parent):
                    await asyncio.sleep(min(0.02, self._cancellation_grace_seconds))
        finally:
            if self._reapers_by_parent.get(parent) is reaper_task:
                self._reapers_by_parent.pop(parent, None)

    def _discard_handler(
        self,
        parent: tuple[str, str],
        task: asyncio.Future[object],
    ) -> None:
        if task.done():
            try:
                task.result()
            except BaseException:
                pass
        tasks = self._handlers_by_parent.get(parent)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._handlers_by_parent.pop(parent, None)

    async def _drain_clients(self, parent: tuple[str, str]) -> None:
        clients = {
            task
            for task in self._clients_by_parent.get(parent, set())
            if not task.done() and task is not asyncio.current_task()
        }
        if clients:
            done, pending = await asyncio.wait(
                clients,
                timeout=self._cancellation_grace_seconds,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=self._cancellation_grace_seconds)
        self._clients_by_parent.pop(parent, None)

    def _discard_client(
        self,
        parent: tuple[str, str],
        task: asyncio.Task | None,
    ) -> None:
        clients = self._clients_by_parent.get(parent)
        if clients is None or task is None:
            return
        clients.discard(task)
        if not clients:
            self._clients_by_parent.pop(parent, None)

    async def _cancel_tasks(self, tasks: set[asyncio.Future[object]]) -> None:
        pending = {task for task in tasks if not task.done()}
        deadline = asyncio.get_running_loop().time() + self._cancellation_grace_seconds
        while pending and asyncio.get_running_loop().time() < deadline:
            for task in pending:
                task.cancel()
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            done, pending = await asyncio.wait(pending, timeout=min(0.02, remaining))
            for task in done:
                try:
                    task.result()
                except BaseException:
                    pass
        for task in pending:
            task.cancel()

    def _reserve_connection(self, parent: tuple[str, str]) -> bool:
        parent_count = self._connections_by_parent.get(parent, 0)
        if (
            self._active_connections >= self._max_connections_global
            or parent_count >= self._max_connections_per_run
        ):
            return False
        self._active_connections += 1
        self._connections_by_parent[parent] = parent_count + 1
        return True

    def _release_connection(self, parent: tuple[str, str]) -> None:
        self._active_connections = max(0, self._active_connections - 1)
        remaining = self._connections_by_parent.get(parent, 0) - 1
        if remaining > 0:
            self._connections_by_parent[parent] = remaining
        else:
            self._connections_by_parent.pop(parent, None)

    @staticmethod
    async def _write_response(
        writer: asyncio.StreamWriter,
        response: dict[str, object],
    ) -> None:
        try:
            writer.write(json.dumps(response, default=str).encode("utf-8") + b"\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def _authorize(
        self,
        token: object,
        *,
        tenant_id: str,
        parent_run_id: str,
        operation: str,
    ) -> _Capability:
        self._require_open()
        if not isinstance(token, str):
            raise CapabilityError("capability rejected")
        capability = self._capabilities.get(token)
        if (
            capability is None
            or capability.tenant_id != tenant_id
            or capability.parent_run_id != parent_run_id
            or capability.operation != operation
            or capability.expires_at <= self._clock()
            or (tenant_id, parent_run_id) not in self._active_parents
        ):
            raise CapabilityError("capability rejected")
        return capability

    def _require_open(self) -> None:
        if self._closed:
            raise CapabilityError("authority is closed")

    @staticmethod
    def _validate_scope(tenant_id: str, parent_run_id: str) -> None:
        if not tenant_id or not _is_safe_run_id(parent_run_id):
            raise ValueError("invalid tenant or parent run scope")
