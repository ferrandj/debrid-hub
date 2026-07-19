from __future__ import annotations

from urllib.parse import quote

import httpx

_URL_RX_SUFFIX = "/manifest.json"


class AddonError(Exception):
    """A configured addon didn't behave like a valid Stremio-protocol addon."""


def base_url(manifest_url: str) -> str:
    """Strip the trailing /manifest.json to get the base every other endpoint
    hangs off, per the protocol (https://github.com/Stremio/stremio-addon-sdk/
    blob/master/docs/protocol.md)."""
    url = manifest_url.strip().rstrip("/")
    if url.endswith(_URL_RX_SUFFIX):
        url = url[: -len(_URL_RX_SUFFIX)]
    return url


async def fetch_manifest(client: httpx.AsyncClient, manifest_url: str) -> dict:
    """GET manifest.json and do the minimum validation that this is actually a
    Stremio addon (has an id/name and at least one resource) before we store
    the URL — catches a pasted-in-wrong-URL early with a clear error instead
    of a cryptic failure later."""
    r = await client.get(manifest_url, follow_redirects=True)
    r.raise_for_status()
    try:
        manifest = r.json()
    except ValueError as exc:
        raise AddonError(f"{manifest_url} did not return JSON") from exc
    if not manifest.get("resources") or not (manifest.get("id") or manifest.get("name")):
        raise AddonError(f"{manifest_url} doesn't look like a Stremio addon manifest")
    return manifest


def summarize_manifest(manifest: dict) -> dict:
    """The non-secret fields worth caching alongside a stored addon URL."""
    return {
        "name": manifest.get("name") or manifest.get("id") or "addon",
        "description": manifest.get("description", ""),
        "resources": [r if isinstance(r, str) else r.get("name") for r in manifest.get("resources", [])],
        "types": manifest.get("types", []),
        "catalogs": [
            {
                "type": c.get("type"),
                "id": c.get("id"),
                "name": c.get("name") or c.get("id"),
                "searchable": any(
                    (e.get("name") if isinstance(e, dict) else e) == "search"
                    for e in c.get("extra", []) or c.get("extraSupported", [])
                ),
            }
            for c in manifest.get("catalogs", [])
        ],
    }


async def fetch_catalog(
    client: httpx.AsyncClient,
    base: str,
    type_: str,
    catalog_id: str,
    *,
    search: str | None = None,
    genre: str | None = None,
    skip: int = 0,
) -> list[dict]:
    """GET /catalog/{type}/{id}[/extra].json -> the `metas` array."""
    extra_parts = []
    if search:
        extra_parts.append(f"search={quote(search, safe='')}")
    if genre:
        extra_parts.append(f"genre={quote(genre, safe='')}")
    if skip:
        extra_parts.append(f"skip={skip}")
    path = f"/catalog/{type_}/{catalog_id}"
    if extra_parts:
        path += "/" + "&".join(extra_parts)
    path += ".json"
    r = await client.get(f"{base}{path}", follow_redirects=True)
    r.raise_for_status()
    return r.json().get("metas", []) or []


async def fetch_meta(client: httpx.AsyncClient, base: str, type_: str, item_id: str) -> dict | None:
    """GET /meta/{type}/{id}.json -> the `meta` object, or None if not found."""
    r = await client.get(f"{base}/meta/{type_}/{item_id}.json", follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("meta")


async def fetch_streams(client: httpx.AsyncClient, base: str, type_: str, item_id: str) -> list[dict]:
    """GET /stream/{type}/{id}.json -> the `streams` array. Read-only per the
    protocol -- addons that resolve to a debrid account do that lazily, when
    a stream's own `url` is later fetched (see trigger_stream), not here."""
    r = await client.get(f"{base}/stream/{type_}/{item_id}.json", follow_redirects=True)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json().get("streams", []) or []


async def trigger_stream(client: httpx.AsyncClient, stream_url: str, *, timeout: float = 60.0) -> int:
    """Fetch a stream's own `url` -- for a debrid-integrated addon this is the
    step that actually resolves/adds the release to the user's account (the
    same thing that happens when Stremio's client hits "Play"). We only need
    the status code; we deliberately don't download the body (some of these
    are 50+ GB video streams)."""
    async with client.stream("GET", stream_url, follow_redirects=True, timeout=timeout) as r:
        return r.status_code
