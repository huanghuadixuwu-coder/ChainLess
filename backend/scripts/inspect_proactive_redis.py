#!/usr/bin/env python3
"""Read-only inspection for retired secret-bearing proactive Redis state."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.proactive.scheduler import inspect_redis_proactive_state


async def main() -> None:
    print(json.dumps(await inspect_redis_proactive_state(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
