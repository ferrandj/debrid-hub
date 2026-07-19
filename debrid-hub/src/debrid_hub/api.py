from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import addons as addons_client
from .aggregator import Aggregator, filter_sort
from .config import Settings, get_settings
from .discover import DiscoverHub

_WEB = Path(__file__).parent / "web" / "index.html"
_CONFIG_FIELDS = ("realdebrid", "alldebrid", "torbox")


class ResolveRequest(BaseModel):
    """Link ids to turn into direct download URLs."""

    ids: list[str] | None = Field(default=None, description="Opaque link ids to resolve.")
    id: str | None = Field(default=None, description="A single link id (shorthand for ids=[id]).")


class DeleteRequest(BaseModel):
    """Link ids to delete from their provider accounts."""

    ids: list[str] | None = Field(default=None, description="Opaque link ids to delete.")
    id: str | None = Field(default=None, description="A single link id (shorthand for ids=[id]).")


class ConfigRequest(BaseModel):
    """Provider API keys to store, encrypted. Omit a field to leave it unchanged;
    send an empty string to clear it."""

    realdebrid: str | None = None
    alldebrid: str | None = None
    torbox: str | None = None


class AddAddonRequest(BaseModel):
    """A Stremio-protocol addon manifest URL to add, encrypted at rest. May
    embed a personal config token in the path -- never returned by any
    endpoint once stored."""

    url: str = Field(description="The addon's manifest.json URL.")


class TriggerRequest(BaseModel):
    """An opaque stream token from GET /api/discover/streams."""

    token: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Debrid Hub", version="1.0.0")
    agg = Aggregator(settings)
    discover = DiscoverHub(settings)

    async def auth(authorization: str | None = Header(default=None)) -> None:
        if settings.api_key and authorization != f"Bearer {settings.api_key}":
            raise HTTPException(status_code=401, detail="Missing or invalid API key.")

    @app.get("/api/providers", dependencies=[Depends(auth)])
    async def providers():
        health = await agg.health()
        caps = agg.provider_caps()
        return {
            "auth_required": bool(settings.api_key),
            "providers": [
                {
                    "name": n,
                    "healthy": health.get(n, False),
                    "capabilities": caps.get(n, []),
                }
                for n in agg.provider_names
            ],
        }

    @app.get("/api/config", dependencies=[Depends(auth)])
    async def get_config():
        """Which provider credentials are set, and from where. Never returns keys."""
        return {
            "providers": agg.credential_status(),
            "encrypted": True,
            "store_error": agg.store_error or None,
        }

    @app.put("/api/config", dependencies=[Depends(auth)])
    async def set_config(body: ConfigRequest):
        """Store provider keys (encrypted). Body: any of realdebrid/alldebrid/torbox.
        An empty value clears that key. Keys not present in the body are unchanged."""
        sent = body.model_dump(exclude_unset=True)
        updates = {k: sent[k] for k in _CONFIG_FIELDS if k in sent}
        if not updates:
            raise HTTPException(
                status_code=400,
                detail=f"Provide at least one of: {', '.join(_CONFIG_FIELDS)}.",
            )
        try:
            agg.set_credentials(updates)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return {"ok": True, "providers": agg.credential_status()}

    @app.delete("/api/config/{provider}", dependencies=[Depends(auth)])
    async def delete_config(provider: str):
        if provider not in _CONFIG_FIELDS:
            raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'.")
        try:
            agg.delete_credential(provider)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return {"ok": True, "providers": agg.credential_status()}

    @app.post("/api/config/reload", dependencies=[Depends(auth)])
    async def reload_config():
        """Re-read the encrypted credential store from disk and rebuild providers
        from it, without changing any key. `GET /api/config` already always
        reflects the file's current contents, but the live providers used for
        listing/resolving/deleting only pick up a change on reload. Use this
        after updating the store out-of-band -- e.g. `debrid-hub config set`
        run via `docker compose exec`, or a pre-encrypted `secrets.enc` dropped
        into the mounted data directory while the server is already running."""
        try:
            agg.reload()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return {"ok": True, "providers": agg.credential_status()}

    @app.get("/api/links", dependencies=[Depends(auth)])
    async def links(
        search: str | None = None,
        provider: str | None = None,
        kind: str | None = None,
        sort: str = "name",
        order: str = "asc",
        refresh: bool = False,
        debug: bool = False,
    ):
        """`debug=true` forces a live refresh and includes, per provider, every
        outbound HTTP call made while listing (method, url, redacted params,
        status, response body) -- for diagnosing a provider API change."""
        all_links = await agg.list_links(force=refresh, debug=debug)
        items = filter_sort(all_links, search, provider, kind, sort, order)
        resp = {
            "count": len(items),
            "total": len(all_links),
            "errors": agg.errors,
            "links": [l.to_dict() for l in items],
        }
        if debug:
            resp["debug"] = agg.debug_logs
        return resp

    @app.post("/api/resolve", dependencies=[Depends(auth)])
    async def resolve(body: ResolveRequest):
        ids = body.ids or ([body.id] if body.id else None)
        if not ids:
            raise HTTPException(status_code=400, detail="Provide 'id' or 'ids'.")
        out: dict[str, dict] = {}
        for link_id in ids:
            try:
                out[link_id] = {"url": await agg.resolve(link_id)}
            except Exception as exc:  # noqa: BLE001
                out[link_id] = {"error": f"{type(exc).__name__}: {exc}"}
        return {"resolved": out}

    @app.post("/api/delete", dependencies=[Depends(auth)])
    async def delete_links(body: DeleteRequest):
        """Delete one or more links from their provider accounts. Per-id result is
        {"ok": true} or {"error": "..."}. Note some providers can only delete a
        whole torrent/magnet, which removes every file inside it."""
        ids = body.ids or ([body.id] if body.id else None)
        if not ids:
            raise HTTPException(status_code=400, detail="Provide 'id' or 'ids'.")
        out: dict[str, dict] = {}
        for link_id in ids:
            try:
                await agg.delete(link_id)
                out[link_id] = {"ok": True}
            except Exception as exc:  # noqa: BLE001
                out[link_id] = {"error": f"{type(exc).__name__}: {exc}"}
        return {"deleted": out}

    # -- Discover: search/browse content via Stremio-protocol addons --------
    # Addon manifest URLs (which commonly embed a personal config token) are
    # encrypted at rest exactly like provider keys and never returned by any
    # endpoint below -- only safe summaries and opaque stream tokens leave
    # this server. See discover.py.

    @app.get("/api/addons", dependencies=[Depends(auth)])
    async def list_addons():
        """Configured content-discovery addons. Never includes the manifest URL."""
        return {"addons": discover.list_addons(), "store_error": discover.store_error or None}

    @app.post("/api/addons", dependencies=[Depends(auth)])
    async def add_addon(body: AddAddonRequest):
        try:
            result = await discover.add_addon(body.url)
        except addons_client.AddonError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=400, detail=f"Could not reach that URL: {exc}")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return {"ok": True, "addon": result}

    @app.delete("/api/addons/{addon_id}", dependencies=[Depends(auth)])
    async def remove_addon(addon_id: str):
        discover.remove_addon(addon_id)
        return {"ok": True}

    @app.get("/api/discover/catalogs", dependencies=[Depends(auth)])
    async def discover_catalogs():
        """Every (addon, catalog) pair -- what the Discover view renders as a
        browsable section, e.g. one per streaming service."""
        return {"sections": discover.catalog_sections()}

    @app.get("/api/discover/catalog", dependencies=[Depends(auth)])
    async def discover_catalog(addon: str, type: str, catalog: str, genre: str | None = None, skip: int = 0):
        try:
            items = await discover.browse(addon, type, catalog, genre=genre, skip=skip)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Addon request failed: {exc}")
        return {"items": items}

    @app.get("/api/discover/search", dependencies=[Depends(auth)])
    async def discover_search(q: str, type: str | None = None):
        if not q.strip():
            raise HTTPException(status_code=400, detail="Provide 'q'.")
        return {"items": await discover.search(q, type_=type)}

    @app.get("/api/discover/meta", dependencies=[Depends(auth)])
    async def discover_meta(type: str, id: str):
        m = await discover.meta(type, id)
        if m is None:
            raise HTTPException(status_code=404, detail="No addon returned metadata for this id.")
        return {"meta": m}

    @app.get("/api/discover/streams", dependencies=[Depends(auth)])
    async def discover_streams(type: str, id: str):
        return {"streams": await discover.streams(type, id)}

    @app.post("/api/discover/add", dependencies=[Depends(auth)])
    async def discover_add(body: TriggerRequest):
        """Resolve a chosen stream -- for a debrid-integrated addon, this is
        the step that actually adds the release to the user's debrid account."""
        try:
            status = await discover.trigger(body.token)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Addon request failed: {exc}")
        ok = 200 <= status < 400
        return {"ok": ok, "status": status}

    @app.get("/health")
    async def health():
        return {"status": "ok", "providers": agg.provider_names}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _WEB.read_text(encoding="utf-8")

    @app.on_event("shutdown")
    async def _shutdown():
        await agg.aclose()
        await discover.aclose()

    return app


app = create_app()
