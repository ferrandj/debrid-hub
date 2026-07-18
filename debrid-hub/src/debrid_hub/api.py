from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from .aggregator import Aggregator, filter_sort
from .config import Settings, get_settings

_WEB = Path(__file__).parent / "web" / "index.html"
_CONFIG_FIELDS = ("realdebrid", "alldebrid", "torbox")


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
        return {
            "auth_required": bool(settings.api_key),
            "providers": [
                {"name": n, "healthy": health.get(n, False)} for n in agg.provider_names
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
    async def set_config(body: dict):
        """Store provider keys (encrypted). Body: any of realdebrid/alldebrid/torbox.
        An empty value clears that key. Keys not present in the body are unchanged."""
        updates = {k: body[k] for k in _CONFIG_FIELDS if k in body}
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
    async def resolve(body: dict):
        ids = body.get("ids")
        if ids is None and body.get("id"):
            ids = [body["id"]]
        if not ids:
            raise HTTPException(status_code=400, detail="Provide 'id' or 'ids'.")
        out: dict[str, dict] = {}
        for link_id in ids:
            try:
                out[link_id] = {"url": await agg.resolve(link_id)}
            except Exception as exc:  # noqa: BLE001
                out[link_id] = {"error": f"{type(exc).__name__}: {exc}"}
        return {"resolved": out}

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
