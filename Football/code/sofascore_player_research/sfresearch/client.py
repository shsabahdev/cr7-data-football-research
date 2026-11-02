"""Polite, cached, resumable client.

Every successful response is stored under <cache_dir>, so an interrupted run
resumes without re-requesting anything, and re-running `report` never touches
the network. Requests are spaced with jitter and back off on blocks.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from .transport import Transport

RETRYABLE = {0, 403, 429, 500, 502, 503, 504}


class BlockedError(RuntimeError):
    """Raised when the site keeps refusing us. Stop instead of hammering it."""


class Client:
    def __init__(
        self,
        transport: Transport,
        cache_dir: Path | str | None,
        delay: tuple[float, float] = (1.5, 3.0),
        max_retries: int = 3,
        backoff: float = 30.0,
        sleep=time.sleep,
        uniform=random.uniform,
    ):
        self.transport = transport
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.delay = delay
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep
        self._uniform = uniform
        self.network_calls = 0
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, path: str) -> Path | None:
        if not self.cache_dir:
            return None
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) + ".json"
        return self.cache_dir / name

    def get(self, path: str) -> dict | None:
        """Return parsed JSON, or None if the resource does not exist (404)."""
        cache_file = self._cache_file(path)
        if cache_file and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return None if cached.get("_status") == 404 else cached

        last_status = None
        for attempt in range(1, self.max_retries + 1):
            self._sleep(self._uniform(*self.delay))
            self.network_calls += 1
            status, data = self.transport.get(path)
            last_status = status
            if status == 200 and data is not None:
                self._store(cache_file, data)
                return data
            if status == 404:
                self._store(cache_file, {"_status": 404})
                return None
            if status in RETRYABLE:
                self._sleep(self.backoff * attempt)
                continue
            raise RuntimeError(f"Unexpected HTTP {status} for {path}")
        detail = getattr(self.transport, "last_detail", "")
        raise BlockedError(
            f"Gave up on {path} after {self.max_retries} tries (last status {last_status}).\n"
            f"  Server said: {detail or 'n/a'}\n"
            "  Try, in order: --transport playwright (real browser), another --impersonate "
            "value, a different network (home connection, no VPN), or wait and slow down "
            "with --delay-min/--delay-max. Progress is cached."
        )

    @staticmethod
    def _store(cache_file: Path | None, data: dict) -> None:
        if cache_file:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
