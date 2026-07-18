from __future__ import annotations

import httpx

from ..models import DebridLink
from .base import Provider

BASE = "https://api.torbox.app/v1/api"

_ID_PARAM = {"torrent": "torrent_id", "webdl": "web_id", "usenet": "usenet_id"}
_DL_PATH = {
    "torrent": "/torrents/requestdl",
    "webdl": "/webdl/requestdl",
    "usenet": "/usenet/requestdl",
}
_LIST = (
    ("torrent", "/torrents/mylist"),
    ("webdl", "/webdl/mylist"),
    ("usenet", "/usenet/mylist"),
)
# Control endpoint + the id field each expects, per kind. Deleting removes the
# whole item (every file inside it), which is all the TorBox API supports.
_CONTROL = {
    "torrent": ("/torrents/controltorrent", "torrent_id"),
    "webdl": ("/webdl/controlwebdownload", "webdl_id"),
    "usenet": ("/usenet/controlusenet", "usenet_id"),
}


class TorBox(Provider):
    """TorBox. Lists torrents, web downloads and usenet items with their files.
    Links are metered, so a direct URL is fetched on demand via requestdl.

    API key: https://torbox.app/settings (Developer / API)
    """

    name = "torbox"
    capabilities = ("delete",)

    def __init__(self, client: httpx.AsyncClient, apikey: str) -> None:
        super().__init__(client)
        self._key = apikey
        self._headers = {"Authorization": f"Bearer {apikey}"}

    async def _get(self, path: str, **params):
        r = await self._client.get(f"{BASE}{path}", headers=self._headers, params=params)
        r.raise_for_status()
        j = r.json()
        if not j.get("success", True):
            raise RuntimeError(j.get("detail") or j.get("error") or "torbox error")
        return j.get("data")

    async def list_links(self) -> list[DebridLink]:
        out: list[DebridLink] = []
        for kind, path in _LIST:
            try:
                data = await self._get(path, bypass_cache="false")
            except Exception:
                continue
            for item in (data or []):
                item_id = item.get("id")
                for f in (item.get("files") or []):
                    out.append(
                        DebridLink(
                            provider=self.name,
                            name=f.get("short_name") or f.get("name") or item.get("name", ""),
                            size=int(f.get("size") or 0),
                            host="torbox",
                            kind=kind,
                            added=item.get("created_at") or item.get("updated_at"),
                            direct_url=None,
                            resolve_hint={"k": kind, "i": item_id, "f": f.get("id")},
                        )
                    )
        return out

    async def resolve(self, hint: dict) -> str:
        kind = hint["k"]
        params = {"token": self._key, _ID_PARAM[kind]: hint["i"], "file_id": hint["f"]}
        r = await self._client.get(f"{BASE}{_DL_PATH[kind]}", params=params)
        r.raise_for_status()
        j = r.json()
        if not j.get("success", True):
            raise RuntimeError(j.get("detail") or "torbox: could not request link")
        return j.get("data")

    async def delete(self, hint: dict) -> None:
        control = _CONTROL.get(hint.get("k"))
        if not control or hint.get("i") is None:
            raise ValueError("torbox: this item cannot be deleted")
        path, id_field = control
        r = await self._client.post(
            f"{BASE}{path}",
            headers=self._headers,
            json={id_field: hint["i"], "operation": "delete"},
        )
        r.raise_for_status()
        j = r.json()
        if not j.get("success", True):
            raise RuntimeError(j.get("detail") or "torbox: delete failed")

    async def health(self) -> bool:
        try:
            await self._get("/user/me")
            return True
        except Exception:
            return False
