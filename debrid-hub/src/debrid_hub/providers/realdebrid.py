from __future__ import annotations

import httpx

from ..models import DebridLink
from .base import Provider

BASE = "https://api.real-debrid.com/rest/1.0"
_TORRENT_READY = "downloaded"


class RealDebrid(Provider):
    """Real-Debrid. Two independent sources of links:

    - /downloads: history of hoster links you've already unrestricted directly.
      Already direct, no extra resolve step.
    - /torrents (+ /torrents/info/{id} for the ready ones): magnets/torrents
      you've added. Each selected file gets a locked link that must go through
      /unrestrict/link, same as a hoster link, to become a direct URL.

    API token: https://real-debrid.com/apitoken
    """

    name = "realdebrid"
    capabilities = ("delete",)

    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        super().__init__(client)
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str, **params):
        url = f"{BASE}{path}"
        r = await self._client.get(url, headers=self._headers, params=params)
        if r.status_code == 204:
            self._record("GET", url, params, r.status_code, [])
            return []
        r.raise_for_status()
        j = r.json()
        self._record("GET", url, params, r.status_code, j)
        return j

    async def list_links(self, force: bool = False) -> list[DebridLink]:
        self._reset_debug()
        out: list[DebridLink] = []

        # Standalone unrestricted downloads (already direct URLs)
        try:
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
                            resolve_hint={
                                "k": "direct",
                                "u": d.get("download"),
                                "del": {"kind": "download", "id": d.get("id")},
                            },
                        )
                    )
                if len(data) < 100:
                    break
                page += 1
        except Exception as exc:  # noqa: BLE001 — surfaced via `warnings`, not swallowed
            self.warnings.append(f"downloads: {type(exc).__name__}: {exc}")

        # Torrents/magnets. Only "downloaded" (ready) ones expose selected
        # files + their locked links, fetched per-torrent via /torrents/info.
        try:
            ready: list[dict] = []
            page = 1
            while page <= 50:
                tdata = await self._get("/torrents", page=page, limit=100)
                if not tdata:
                    break
                ready.extend(t for t in tdata if t.get("status") == _TORRENT_READY)
                if len(tdata) < 100:
                    break
                page += 1

            for t in ready:
                tid = t.get("id")
                try:
                    info = await self._get(f"/torrents/info/{tid}")
                except Exception as exc:  # noqa: BLE001
                    self.warnings.append(f"torrent {tid}: {type(exc).__name__}: {exc}")
                    continue
                files = [f for f in (info.get("files") or []) if f.get("selected")]
                links = info.get("links") or []
                # RD returns `links` in the same order as the selected files.
                for f, link in zip(files, links):
                    path = (f.get("path") or "").lstrip("/")
                    name = path.rsplit("/", 1)[-1] if path else info.get("filename", "")
                    out.append(
                        DebridLink(
                            provider=self.name,
                            name=name or info.get("filename", ""),
                            size=int(f.get("bytes") or 0),
                            host="real-debrid",
                            kind="torrent",
                            added=info.get("added") or t.get("added"),
                            direct_url=None,
                            resolve_hint={
                                "k": "restrict",
                                "u": link,
                                "del": {"kind": "torrent", "id": tid},
                            },
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"torrents: {type(exc).__name__}: {exc}")

        return out

    async def resolve(self, hint: dict) -> str:
        if hint.get("k") == "direct" and hint.get("u"):
            return hint["u"]
        if hint.get("k") == "restrict":
            url = f"{BASE}/unrestrict/link"
            r = await self._client.post(url, headers=self._headers, data={"link": hint["u"]})
            r.raise_for_status()
            j = r.json()
            self._record("POST", url, {"link": hint["u"]}, r.status_code, j)
            return j["download"]
        raise ValueError("real-debrid: unresolvable link")

    async def delete(self, hint: dict) -> None:
        d = hint.get("del") or {}
        did = d.get("id")
        if not did:
            raise ValueError("real-debrid: this link has no delete id")
        path = "/torrents/delete/" if d.get("kind") == "torrent" else "/downloads/delete/"
        url = f"{BASE}{path}{did}"
        r = await self._client.delete(url, headers=self._headers)
        self._record("DELETE", url, {}, r.status_code, "")
        if r.status_code not in (200, 202, 204):
            r.raise_for_status()

    async def health(self) -> bool:
        try:
            await self._get("/user")
            return True
        except Exception:
            return False
