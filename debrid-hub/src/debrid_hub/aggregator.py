from __future__ import annotations

import asyncio
import time

import httpx

from .config import Settings
from .models import DebridLink, decode_id
from .providers.alldebrid import AllDebrid
from .providers.base import Provider
from .providers.mock import Mock
from .providers.realdebrid import RealDebrid
from .providers.torbox import TorBox

_SORT_KEYS = {
    "name": lambda l: (l.name or "").lower(),
    "size": lambda l: l.size,
    "host": lambda l: (l.host or "").lower(),
    "provider": lambda l: l.provider,
    "added": lambda l: l.added or "",
    "kind": lambda l: l.kind,
}


def filter_sort(
    links: list[DebridLink],
    search: str | None = None,
    provider: str | None = None,
    kind: str | None = None,
    sort: str = "name",
    order: str = "asc",
) -> list[DebridLink]:
    items = links
    if provider:
        items = [l for l in items if l.provider == provider]
    if kind:
        items = [l for l in items if l.kind == kind]
    if search:
        q = search.lower()
        items = [l for l in items if q in (l.name or "").lower() or q in (l.host or "").lower()]
    key = _SORT_KEYS.get(sort, _SORT_KEYS["name"])
    return sorted(items, key=key, reverse=(order == "desc"))


class Aggregator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout)
        self._providers: dict[str, Provider] = {}
        self._cache: list[DebridLink] | None = None
        self._cache_at = 0.0
        self.errors: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        s = self.settings
        if s.realdebrid_token:
            self._providers["realdebrid"] = RealDebrid(self._client, s.realdebrid_token)
        if s.alldebrid_apikey:
            self._providers["alldebrid"] = AllDebrid(self._client, s.alldebrid_apikey)
        if s.torbox_apikey:
            self._providers["torbox"] = TorBox(self._client, s.torbox_apikey)
        if s.enable_mock:
            self._providers["mock"] = Mock(self._client)

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers)

    async def list_links(self, force: bool = False) -> list[DebridLink]:
        now = time.time()
        if not force and self._cache is not None and now - self._cache_at < self.settings.cache_ttl:
            return self._cache

        names = list(self._providers)
        results = await asyncio.gather(
            *(p.list_links() for p in self._providers.values()),
            return_exceptions=True,
        )
        links: list[DebridLink] = []
        errors: dict[str, str] = {}
        for name, res in zip(names, results):
            if isinstance(res, Exception):
                errors[name] = f"{type(res).__name__}: {res}"
                continue
            for l in res:
                l.id = l.compute_id()
                links.append(l)
        self._cache, self._cache_at, self.errors = links, now, errors
        return links

    async def resolve(self, link_id: str) -> str:
        info = decode_id(link_id)
        provider = self._providers.get(info["p"])
        if provider is None:
            raise KeyError(f"provider '{info['p']}' is not configured")
        return await provider.resolve(info["h"])

    async def health(self) -> dict[str, bool]:
        names = list(self._providers)
        results = await asyncio.gather(
            *(p.health() for p in self._providers.values()),
            return_exceptions=True,
        )
        return {n: (r is True) for n, r in zip(names, results)}

    async def aclose(self) -> None:
        await self._client.aclose()
