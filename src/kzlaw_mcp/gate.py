"""Per-client rate limit, a global cap on concurrent tool work, and a JSONL call log."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import anyio.to_thread

from kzlaw_mcp.config import Settings
from kzlaw_mcp.corpus import InputError
from kzlaw_mcp.gitio import CommandError

if TYPE_CHECKING:
    from starlette.requests import Request


class RateLimiter:
    def __init__(
        self, calls: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.calls, self.window, self._clock = calls, window_s, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        with self._lock:
            now = self._clock()
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.calls:
                return self.window - (now - q[0])
            q.append(now)
            if len(self._hits) > 10_000:
                self._hits = {
                    k: v for k, v in self._hits.items() if v and now - v[-1] < self.window
                }
            return None


class CallLog:
    def __init__(self, path: Path | None, salt: str) -> None:
        self.path, self.salt = path, salt
        self._lock = threading.Lock()

    def record(self, *, ip: str, **fields: Any) -> None:
        if self.path is None:
            return
        row = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "ip": hashlib.sha256(f"{self.salt}{ip}".encode()).hexdigest()[:16],
            **fields,
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def client_ip(request: Request | None, trusted: frozenset[str]) -> tuple[str, bool]:
    """The client's address. X-Forwarded-For counts only when the peer is our proxy, and then
    only its last entry: Caddy appends the address it saw, anything before it is client-supplied."""
    if request is None:
        return "local", False
    peer = request.client.host if request.client else "unknown"
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip(), True
    return peer, False


class Gate:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic) -> None:
        if settings.log_path is not None and not settings.ip_salt:
            # sha256 of a bare IPv4 address is reversed by trying all 2**32 of them
            raise ValueError("set KZLAW_IP_SALT to a random value when the call log is on")
        self.settings = settings
        self.limiter = RateLimiter(settings.rate_calls, settings.rate_window_s, clock)
        self.log = CallLog(settings.log_path, settings.ip_salt)
        self._capacity: anyio.CapacityLimiter | None = None

    async def call(
        self, tool: str, args: dict, request: Request | None, fn: Callable[[], dict]
    ) -> dict:
        if self._capacity is None:
            self._capacity = anyio.CapacityLimiter(self.settings.max_parallel)
        ip, via_proxy = client_ip(request, self.settings.trusted_proxies)
        base = {"ip": ip, "via_proxy": via_proxy, "tool": tool}
        wait = self.limiter.hit(ip)
        if wait is not None:  # logged without args: a limited caller cannot fill the disk
            self.log.record(**base, ok=False, error="rate_limited", ms=0)
            raise InputError(f"rate limit reached; try again in {int(wait) + 1} s")
        base["args"] = _clip_args(args)
        started = time.monotonic()
        try:
            result = await anyio.to_thread.run_sync(fn, limiter=self._capacity)
        except InputError as exc:
            self.log.record(**base, ok=False, error=str(exc), ms=_ms(started))
            raise
        except CommandError as exc:
            self.log.record(**base, ok=False, error=str(exc), ms=_ms(started))
            raise InputError(f"temporary failure, try again: {exc}") from exc
        except Exception as exc:  # logged for review; the client gets no paths or traces
            self.log.record(**base, ok=False, error=type(exc).__name__, ms=_ms(started))
            raise InputError("internal error; try again or rephrase") from exc
        size = len(json.dumps(result, ensure_ascii=False))
        self.log.record(**base, ok=True, size=size, ms=_ms(started))
        return result


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _clip_args(args: dict, limit: int = 300) -> dict:
    """Arguments as logged: long strings cut, lists capped. Inputs are checked only later."""

    def clip(v: object, n: int = limit) -> object:
        if isinstance(v, str):
            return v[:n]
        if isinstance(v, list):  # scopes: at most 25 names of under 40 characters
            return [clip(x, 40) for x in v[:30]]
        return v

    return {k: clip(v) for k, v in args.items()}
