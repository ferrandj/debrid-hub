from __future__ import annotations

import httpx

from ..models import DebridLink
from .base import Provider

BASE = "https://api.real-debrid.com/rest/1.0"


class RealDebrid(Provider):
    """Real-Debrid. Uses the /downloads history, which already contains direct,
    unrestricted URLs -- so those need no extra resolve step.

    API token: https://real-debrid.com/apitoken
    """

    name = "realdebrid"

    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        super().__init__(client)
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str, **params):
        r = await self._client.get(f"{BASE}{path}", headers=self._headers, params=params)
        if r.status_code == 204:
            return []
        r.raise_for_status()
        return r.json()

    async def list_links(self) -> list[DebridLink]:
        out: list[DebridLink] = []
        page = 1
        while page <= 50:  # hard cap: 50 pages * 100 = 5000 items
            data = await self._get("/downloads", page=page, limit=100)
            if not data:
                break
            for d in data:
                out.append(
                    DebridLink(
                        provider=self.name,
                        name=d.get("filename") or d.get("link", ""),
                        size=int(d.get("filesize") or 0),
                        host=d.get("host", ""),
                        kind="download",
                        added=d.get("generated"),
                        direct_url=d.get("download"),
                        resolve_hint={"k": "direct", "u": d.get("download")},
                    )
                )
            if len(data) < 100:
                break
            page += 1
        return out

    async def resolve(self, hint: dict) -> str:
        if hint.get("k") == "direct" and hint.get("u"):
            return hint["u"]
        if hint.get("k") == "restrict":
            r = await self._client.post(
                f"{BASE}/unrestrict/link",
                headers=self._headers,
                data={"link": hint["u"]},
            )
            r.raise_for_status()
            return r.json()["download"]
        raise ValueError("real-debrid: unresolvable link")

    async def health(self) -> bool:
        try:
            await self._get("/user")
            return True
        except Exception:
            return False
