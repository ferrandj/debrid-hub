from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import urlparse

import httpx

from . import addons
from .config import Settings
from .models import decode_id
from .store import AddonStore


def _encode_token(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class DiscoverHub:
    """Search/browse/stream across configured Stremio-protocol addons, and
    trigger a chosen stream (which is how a debrid-integrated addon actually
    adds the release to the user's account -- see addons.trigger_stream).

    Addon manifest URLs are encrypted at rest (AddonStore) and never leave the
    server: every API surface here returns either safe summaries or opaque
    tokens standing in for a stream's real url, which trigger() decodes and
    validates server-side (the host must match the addon it claims to be from,
    so a forged/tampered token can't be used to make the server fetch an
    arbitrary attacker-chosen host)."""

    def __init__(self, settings: Settings, store: AddonStore | None = None) -> None:
        self.settings = settings
        self._store = store or AddonStore(settings.data_dir, settings.secret_key)
        self._client = httpx.AsyncClient(timeout=settings.request_timeout)
        self.store_error: str = ""

    # -- addon management ---------------------------------------------------
    def list_addons(self) -> list[dict]:
        """Safe summaries only -- the url itself is never included."""
        try:
            data = self._store.load()
            self.store_error = ""
        except Exception as exc:  # noqa: BLE001
            self.store_error = str(exc)
            return []
        return [
            {k: v for k, v in entry.items() if k != "url"}
            for entry in sorted(data.values(), key=lambda e: e.get("name", ""))
        ]

    async def add_addon(self, manifest_url: str) -> dict:
        manifest_url = manifest_url.strip()
        manifest = await addons.fetch_manifest(self._client, manifest_url)
        summary = addons.summarize_manifest(manifest)
        aid = self._store.upsert(manifest_url, summary)
        return {"id": aid, **summary}

    def remove_addon(self, addon_id: str) -> None:
        self._store.delete(addon_id)

    def _addons(self) -> dict[str, dict]:
        return self._store.load()

    # -- discover -------------------------------------------------------
    def catalog_sections(self) -> list[dict]:
        """One entry per (addon, catalog) -- what the Discover view renders as
        a browsable section, e.g. "Streaming Catalogs / Netflix"."""
        out = []
        for entry in self._addons().values():
            for cat in entry.get("catalogs", []):
                out.append(
                    {
                        "addon_id": entry["id"],
                        "addon_name": entry.get("name", ""),
                        "type": cat.get("type"),
                        "catalog_id": cat.get("id"),
                        "name": cat.get("name"),
                    }
                )
        return out

    async def browse(self, addon_id: str, type_: str, catalog_id: str, *, genre: str | None = None, skip: int = 0) -> list[dict]:
        url = self._store.get_url(addon_id)
        if not url:
            raise KeyError(f"unknown addon '{addon_id}'")
        base = addons.base_url(url)
        metas = await addons.fetch_catalog(self._client, base, type_, catalog_id, genre=genre, skip=skip)
        return [_slim_meta(m) for m in metas]

    async def search(self, query: str, type_: str | None = None) -> list[dict]:
        """Fan out to every configured catalog that declares search support,
        across every addon, in parallel. One addon failing doesn't break the
        rest. Results are deduped by id, first hit wins."""
        jobs = []
        for entry in self._addons().values():
            base = addons.base_url(entry["url"])
            for cat in entry.get("catalogs", []):
                if not cat.get("searchable"):
                    continue
                if type_ and cat.get("type") != type_:
                    continue
                jobs.append(addons.fetch_catalog(self._client, base, cat["type"], cat["id"], search=query))
        if not jobs:
            return []
        results = await asyncio.gather(*jobs, return_exceptions=True)
        seen: dict[str, dict] = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            for m in res:
                mid = m.get("id")
                if mid and mid not in seen:
                    seen[mid] = _slim_meta(m)
        return list(seen.values())

    async def meta(self, type_: str, item_id: str) -> dict | None:
        """Query every addon with a `meta` resource in parallel, then merge:
        first addon to report a field wins it, later addons only fill gaps.
        Combines e.g. Cinemeta's trailer with AIOMetadata's cast photos."""
        jobs = [
            addons.fetch_meta(self._client, addons.base_url(entry["url"]), type_, item_id)
            for entry in self._addons().values()
            if "meta" in entry.get("resources", [])
        ]
        if not jobs:
            return None
        results = await asyncio.gather(*jobs, return_exceptions=True)
        merged: dict = {}
        for res in results:
            if isinstance(res, Exception) or not res:
                continue
            for k, v in res.items():
                if k not in merged or merged[k] in (None, "", [], {}):
                    merged[k] = v
        return merged or None

    async def streams(self, type_: str, item_id: str) -> list[dict]:
        """Query every addon with a `stream` resource in parallel. Each
        returned stream's real url is replaced with an opaque token (see
        trigger()) before this ever reaches the API/browser."""
        entries = [e for e in self._addons().values() if "stream" in e.get("resources", [])]
        jobs = [
            addons.fetch_streams(self._client, addons.base_url(e["url"]), type_, item_id) for e in entries
        ]
        if not jobs:
            return []
        results = await asyncio.gather(*jobs, return_exceptions=True)
        out: list[dict] = []
        for entry, res in zip(entries, results):
            if isinstance(res, Exception):
                continue
            for s in res:
                url = s.get("url")
                if not url:
                    continue  # some streams are magnet/infoHash-only, not a fetchable url -- skip for now
                bh = s.get("behaviorHints", {}) or {}
                out.append(
                    {
                        "addon_id": entry["id"],
                        "addon_name": entry.get("name", ""),
                        "name": s.get("name", ""),
                        "description": s.get("description") or s.get("title") or "",
                        "size": bh.get("videoSize"),
                        "filename": bh.get("filename"),
                        "token": _encode_token({"a": entry["id"], "u": url}),
                    }
                )
        return out

    async def trigger(self, token: str) -> int:
        """Fetch a stream's real url -- the step that actually resolves/adds
        it to the user's debrid account for addons that work that way. Host
        of the embedded url must match the addon it claims to come from."""
        info = decode_id(token)
        addon_id, url = info["a"], info["u"]
        addon_url = self._store.get_url(addon_id)
        if not addon_url:
            raise KeyError(f"unknown addon '{addon_id}'")
        if urlparse(url).hostname != urlparse(addon_url).hostname:
            raise ValueError("stream url host does not match its addon")
        return await addons.trigger_stream(self._client, url)

    async def aclose(self) -> None:
        await self._client.aclose()


def _slim_meta(m: dict) -> dict:
    """A catalog entry's fields worth showing in a poster grid -- catalog
    responses can carry a lot more than this, trimmed here."""
    return {
        "id": m.get("id"),
        "type": m.get("type"),
        "name": m.get("name"),
        "poster": m.get("poster"),
        "year": m.get("releaseInfo") or m.get("year"),
        "description": m.get("description"),
        "imdbRating": m.get("imdbRating"),
    }
