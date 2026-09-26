"""Runtime settings, read from KZLAW_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SCOPES: tuple[str, ...] = ("codes", "government", "ministerial")
LOCAL_SCOPES: tuple[str, ...] = tuple(
    f"local-{name}"
    for name in (
        "abai",
        "akmola",
        "aktobe",
        "almaty-city",
        "almaty-oblast",
        "astana",
        "atyrau",
        "central",
        "east-kazakhstan",
        "joint",
        "karaganda",
        "kostanay",
        "kyzylorda",
        "mangystau",
        "north-kazakhstan",
        "pavlodar",
        "shymkent",
        "turkestan",
        "ulytau",
        "west-kazakhstan",
        "zhambyl",
        "zhetisu",
    )
)
ALL_SCOPES: tuple[str, ...] = DEFAULT_SCOPES + LOCAL_SCOPES


@dataclass(frozen=True)
class Settings:
    corpus_root: Path
    github_org: str = "kazakhstan-law"
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = "http://127.0.0.1:8000/mcp"
    trusted_proxies: frozenset[str] = field(default_factory=lambda: frozenset({"100.64.0.1"}))
    log_path: Path | None = None
    ip_salt: str = ""
    rate_calls: int = 300
    rate_window_s: float = 600.0
    max_parallel: int = 6
    subprocess_timeout_s: float = 20.0
    head_ttl_s: float = 60.0
    remote_template: str = "https://github.com/{org}/{scope}.git"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        log = env.get("KZLAW_LOG_PATH")
        proxies = env.get("KZLAW_TRUSTED_PROXIES", "100.64.0.1")
        return cls(
            corpus_root=Path(env.get("KZLAW_CORPUS_ROOT", "/corpus")),
            github_org=env.get("KZLAW_GITHUB_ORG", "kazakhstan-law"),
            host=env.get("KZLAW_HOST", "127.0.0.1"),
            port=int(env.get("KZLAW_PORT", "8000")),
            public_url=env.get("KZLAW_PUBLIC_URL", "http://127.0.0.1:8000/mcp"),
            trusted_proxies=frozenset(p.strip() for p in proxies.split(",") if p.strip()),
            log_path=Path(log) if log else None,
            ip_salt=env.get("KZLAW_IP_SALT", ""),
            rate_calls=int(env.get("KZLAW_RATE_CALLS", "300")),
            rate_window_s=float(env.get("KZLAW_RATE_WINDOW_S", "600")),
            max_parallel=int(env.get("KZLAW_MAX_PARALLEL", "6")),
            subprocess_timeout_s=float(env.get("KZLAW_SUBPROCESS_TIMEOUT_S", "20")),
            head_ttl_s=float(env.get("KZLAW_HEAD_TTL_S", "60")),
            remote_template=env.get(
                "KZLAW_REMOTE_TEMPLATE", "https://github.com/{org}/{scope}.git"
            ),
        )
