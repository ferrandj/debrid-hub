from __future__ import annotations

import httpx

from ..models import DebridLink
from . import unix_to_iso
from .base import Provider

BASE = "https://api.alldebrid.com/v4"
AGENT = "debrid-hub"


class AllDebrid(Provider):
    """AllDebrid. Lists saved links plus files inside completed magnets.
    Every link is "locked" and must be resolved through /link/unlock to get a
    direct URL.

    API key: https://alldebrid.com/apikeys/
    """

    name = "alldebrid"

    def __init__(self, client: httpx.AsyncClient, apikey: str) -> None:
        super().__init__(client)
        self._auth = {"agent": AGENT, "apikey": apikey}

    async def _get(self, path: str, **params):
        r = await self._client.get(f"{BASE}{path}", params={**self._auth, **params})
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "success":
            err = j.get("error", {})
            raise RuntimeError(err.get("message") or err.get("code") or "alldebrid error")
        return j.get("data", {})

    async def list_links(self) -> list[DebridLink]:
        out: list[DebridLink] = []

        # Saved links
        try:
            data = await self._get("/user/links")
            for l in data.get("links", []):
                out.append(
                    DebridLink(
                        provider=self.name,
                        name=l.get("filename") or l.get("link", ""),
                        size=int(l.get("size") or 0),
                        host=l.get("host", ""),
                        kind="saved",
                        added=unix_to_iso(l.get("date")),
                        direct_url=None,
                        resolve_hint={"k": "unlock", "u": l["link"]},
                    )
                )
        except Exception:
            pass

        # Files inside completed magnets
        try:
            data = await self._get("/magnet/status")
            magnets = data.get("magnets", [])
            if isinstance(magnets, dict):
                magnets = list(magnets.values())
            for m in magnets:
                for f in (m.get("links") or []):
                    out.append(
                        DebridLink(
                            provider=self.name,
                            name=f.get("filename") or m.get("filename", ""),
                            size=int(f.get("size") or 0),
                            host="alldebrid",
                            kind="magnet",
                            added=unix_to_iso(m.get("completionDate") or m.get("uploadDate")),
                            direct_url=None,
                            resolve_hint={"k": "unlock", "u": f["link"]},
                        )
                    )
        except Exception:
            pass

        return out

    async def resolve(self, hint: dict) -> str:
        data = await self._get("/link/unlock", link=hint["u"])
        return data["link"]

    async def health(self) -> bool:
        try:
            await self._get("/user")
            return True
        except Exception:
            return False
