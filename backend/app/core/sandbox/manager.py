"""Real SandboxManager — talks to sandbox-proxy over HTTP to manage container pool."""

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Maximum number of executions on a single container before recycling.
_MAX_EXECUTIONS = 50
# Maximum lifetime (seconds) for an allocated container before it must be replaced.
_MAX_LIFETIME_SECONDS = 600


class SandboxManager:
    """Pool manager for sandbox containers.

    Delegates container lifecycle to the *sandbox-proxy* HTTP service.  The
    proxy is a separate FastAPI process that manages Docker containers directly.
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        self._proxy_url = settings.sandbox_proxy_url.rstrip("/")
        self._auth_token = settings.proxy_auth_token
        self._pool_min = settings.sandbox_pool_min
        self._pool_max = settings.sandbox_pool_max
        self._pool_size: int = 0

        # httpx client (created lazily in warm_pool / allocate)
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._proxy_url,
                headers={"Authorization": f"Bearer {self._auth_token}"},
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Send a request to the sandbox-proxy and raise on non-2xx."""
        client = self._get_client()
        resp = await client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            body = resp.text[:500]
            logger.warning("sandbox-proxy error %s %s -> %s: %s", method, path, resp.status_code, body)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    async def warm_pool(self) -> None:
        """Tell the proxy to warm *pool_min* containers."""
        target = self._pool_min
        logger.info("Warming sandbox pool (min=%d)", target)

        # The proxy already warms the pool on startup; we just verify
        # connectivity and check the pool size.
        try:
            await self.get_proxy_health()
            logger.info("Sandbox proxy healthy — pool_size=%d", self._pool_size)
        except Exception as exc:
            logger.warning("Could not contact sandbox-proxy: %s", exc)
            self._pool_size = 0

        # If the pool is under target, allocate additional containers
        # and immediately recycle them so they sit idle.
        for _ in range(max(0, target - self._pool_size)):
            try:
                alloc = await self._request("POST", "/containers/allocate")
                cid = alloc.json().get("container_id")
                if cid:
                    await self._request("POST", f"/containers/{cid}/recycle")
                    self._pool_size = min(self._pool_max, self._pool_size + 1)
            except Exception as exc:
                logger.warning("Failed to warm additional container: %s", exc)

    @property
    def pool_size(self) -> int:
        return self._pool_size

    async def get_proxy_health(self) -> dict:
        """Fetch live health data from sandbox-proxy and refresh cache."""
        resp = await self._request("GET", "/health")
        data = resp.json()
        self._pool_size = data.get("pool_size", 0)
        return data

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    async def allocate(self) -> str:
        """Obtain a healthy container id from the pool.

        The container is health-checked (ping).  If it fails the check, a new
        one is created automatically.
        """
        resp = await self._request("POST", "/containers/allocate")
        data = resp.json()
        cid = data["container_id"]
        logger.info("Allocated container %s", cid)
        self._pool_size = max(0, self._pool_size - 1)
        return cid

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, cid: str, script: str, timeout: int = 30) -> AsyncIterator[dict]:
        """Execute *script* in container *cid*.

        Yields dicts with keys ``type`` (``"stdout"`` / ``"stderr"`` / ``"error"`` / ``"done"``)
        and ``data`` (str).
        """
        client = self._get_client()
        async with client.stream(
            "POST",
            f"/containers/{cid}/execute",
            json={"script": script, "timeout": timeout},
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                yield {"type": "error", "data": body.decode("utf-8", errors="replace")}
                return

            event_type = ""
            event_data = ""
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    event_data = line[len("data: "):]
                elif line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line == "":
                    # SSE blank line — event delimiter (end of one event)
                    if event_type == "done":
                        yield {"type": "done", "data": ""}
                        return
                    elif event_type == "error":
                        yield {"type": "error", "data": event_data}
                    elif event_data:
                        yield {"type": "stdout", "data": event_data}
                    event_type = ""
                    event_data = ""

            # If stream ended without a done event
            yield {"type": "done", "data": ""}

    async def execute_disposable_parent(
        self,
        *,
        run_id: str,
        capability: str,
        script: str,
        timeout: int = 30,
    ) -> dict:
        """Execute once in a run-bound parent sandbox that the proxy must delete."""
        try:
            response = await self._request(
                "POST",
                "/parent-runs/execute",
                json={
                    "run_id": run_id,
                    "capability": capability,
                    "script": script,
                    "timeout": timeout,
                },
            )
        except asyncio.CancelledError as cancellation:
            await self._cancel_disposable_parent_authoritatively(run_id, capability)
            raise cancellation
        except Exception as execution_error:
            await self._annotate_disposable_parent_cleanup(
                execution_error,
                run_id,
                capability,
            )
            raise
        data = response.json()
        self._require_disposable_parent_deleted(data)
        return data

    async def _annotate_disposable_parent_cleanup(
        self,
        execution_error: Exception,
        run_id: str,
        capability: str,
    ) -> None:
        """Attach authoritative cleanup evidence without replacing execute errors."""
        try:
            status = await self._request(
                "POST",
                f"/parent-runs/{run_id}/status",
                json={"capability": capability},
            )
            data = status.json()
            self._require_disposable_parent_deleted(data)
        except BaseException as cleanup_error:
            execution_error.disposable_parent_deleted = False
            execution_error.disposable_parent_cleanup_error = cleanup_error
            if hasattr(execution_error, "add_note"):
                execution_error.add_note(
                    f"disposable parent cleanup verification failed: {cleanup_error}"
                )
            return
        execution_error.disposable_parent_deleted = True
        execution_error.disposable_parent_cleanup_status = data

    async def _cancel_disposable_parent_authoritatively(
        self,
        run_id: str,
        capability: str,
    ) -> None:
        async def cancel_and_confirm() -> None:
            cancel_response = await self._request(
                "POST",
                f"/parent-runs/{run_id}/cancel",
                json={"capability": capability},
            )
            self._require_disposable_parent_deleted(cancel_response.json())
            status = await self._request(
                "POST",
                f"/parent-runs/{run_id}/status",
                json={"capability": capability},
            )
            self._require_disposable_parent_deleted(status.json())

        control = asyncio.create_task(cancel_and_confirm())
        while not control.done():
            try:
                await asyncio.shield(control)
            except asyncio.CancelledError:
                continue
        control.result()

    @staticmethod
    def _require_disposable_parent_deleted(data: dict) -> None:
        container_id = data.get("container_id")
        active_container_ids = data.get("active_container_ids")
        cleanup_errors = data.get("cleanup_errors")
        cleanup_confirmed = (
            data.get("deleted") is True
            and isinstance(cleanup_errors, list)
            and not cleanup_errors
            and isinstance(container_id, str)
            and bool(container_id)
            and isinstance(active_container_ids, list)
            and all(isinstance(cid, str) for cid in active_container_ids)
            and container_id not in active_container_ids
        )
        if not cleanup_confirmed:
            raise RuntimeError(
                f"disposable parent cleanup not confirmed: {data!r}"
            )

    # ------------------------------------------------------------------
    # Recycle / cleanup
    # ------------------------------------------------------------------

    async def recycle(self, cid: str) -> str:
        """Return container to the idle pool (or replace if expired).

        Returns the (possibly new) container id.
        """
        resp = await self._request("POST", f"/containers/{cid}/recycle")
        data = resp.json()
        new_cid = data.get("container_id", cid)
        self._pool_size = min(self._pool_max, self._pool_size + 1)
        logger.info("Recycled container %s -> %s", cid, new_cid)
        return new_cid

    async def close(self) -> None:
        """Graceful shutdown — close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._pool_size = 0
        logger.info("Sandbox manager closed")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_sandbox_manager() -> SandboxManager:
    """FastDI dependency that returns the global SandboxManager instance.

    Usage in a route handler::

        from app.core.sandbox import get_sandbox_manager

        @router.post("/execute")
        async def run_code(sbox: SandboxManager = Depends(get_sandbox_manager)):
            ...
    """
    # Import here to avoid circular imports.
    from app.main import app_state

    assert app_state.sandbox_manager is not None, "SandboxManager not initialised"
    return app_state.sandbox_manager
