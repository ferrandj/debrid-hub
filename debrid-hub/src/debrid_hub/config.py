from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class Settings:
    realdebrid_token: str = ""
    alldebrid_apikey: str = ""
    torbox_apikey: str = ""
    api_key: str = ""            # optional bearer to protect the exposed API/UI
    cache_ttl: int = 60          # seconds to cache the aggregated listing
    request_timeout: float = 30.0
    enable_mock: bool = False    # inject a demo provider (no keys needed)
    data_dir: str = ""           # where the encrypted credential store lives
    secret_key: str = ""         # master key for the store (else auto-generated)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def default_data_dir() -> str:
    """Directory holding the encrypted credential store. Override with
    DEBRID_HUB_DATA_DIR (mount a volume for this in Docker to persist keys)."""
    env = os.getenv("DEBRID_HUB_DATA_DIR", "").strip()
    return env or str(Path.home() / ".config" / "debrid-hub")


@lru_cache
def get_settings() -> Settings:
    return Settings(
        realdebrid_token=os.getenv("DEBRID_REALDEBRID_TOKEN", "").strip(),
        alldebrid_apikey=os.getenv("DEBRID_ALLDEBRID_APIKEY", "").strip(),
        torbox_apikey=os.getenv("DEBRID_TORBOX_APIKEY", "").strip(),
        api_key=os.getenv("DEBRID_HUB_API_KEY", "").strip(),
        cache_ttl=int(os.getenv("DEBRID_HUB_CACHE_TTL", "60")),
        request_timeout=float(os.getenv("DEBRID_HUB_TIMEOUT", "30")),
        enable_mock=_flag("DEBRID_HUB_MOCK"),
        data_dir=default_data_dir(),
        secret_key=os.getenv("DEBRID_HUB_SECRET_KEY", "").strip(),
    )
