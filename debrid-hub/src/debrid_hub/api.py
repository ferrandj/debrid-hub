from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .aggregator import Aggregator, filter_sort
from .config import Settings, get_settings

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Debrid Hub", version="1.0.0")
    agg = Aggregator(settings)

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

    @app.get("/api/links", dependencies=[Depends(auth)])
    async def links(
        search: str | None = None,
        provider: str | None = None,
        kind: str | None = None,
        sort: str = "name",
        order: str = "asc",
        refresh: bool = False,
    ):
        all_links = await agg.list_links(force=refresh)
        items = filter_sort(all_links, search, provider, kind, sort, order)
        return {
            "count": len(items),
            "total": len(all_links),
            "errors": agg.errors,
            "links": [l.to_dict() for l in items],
        }

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

    @app.get("/health")
    async def health():
        return {"status": "ok", "providers": agg.provider_names}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _WEB.read_text(encoding="utf-8")

    @app.on_event("shutdown")
    async def _shutdown():
        await agg.aclose()

    return app


app = create_app()
