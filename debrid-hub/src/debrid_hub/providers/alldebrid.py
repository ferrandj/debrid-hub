from __future__ import annotations

import httpx

from ..models import DebridLink
from . import unix_to_iso
from .base import Provider

BASE = "https://api.alldebrid.com/v4"
# AllDebrid discontinued the old /v4/magnet/status (it used to also carry each
# magnet's files). It's now split: v4.1/magnet/status returns status only, and
# the files/links for ready magnets must be fetched separately from
# v4/magnet/files. See https://docs.alldebrid.com.
BASE_V41 = "https://api.alldebrid.com/v4.1"
AGENT = "debrid-hub"
_READY = 4  # magnet/status statusCode meaning "Ready" (files available)
_CHUNK = 50  # magnet ids per magnet/files call


def _flatten_files(entries: list[dict]):
    """magnet/files entries are either a leaf ({"n","s","l"}) or a folder
    ({"n","e":[...]}) that nests more of the same, recursively."""
    for e in entries or []:
        if e.get("e"):
            yield from _flatten_files(e["e"])
        elif e.get("l"):
            yield e


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class AllDebrid(Provider):
    """AllDebrid. Lists saved links plus files inside completed magnets.
    Every link is "locked" and must be resolved through /link/unlock to get a
    direct URL.

    API key: https://alldebrid.com/apikeys/
    """

    name = "alldebrid"
    capabilities = ("delete",)

    def __init__(self, client: httpx.AsyncClient, apikey: str) -> None:
        super().__init__(client)
        self._auth = {"agent": AGENT, "apikey": apikey}

    async def _call(self, base: str, path: str, method: str = "GET", **params) -> dict:
        merged = {**self._auth, **params}
        url = f"{base}{path}"
        r = await self._client.request(method, url, params=merged)
        status = r.status_code
        r.raise_for_status()
        j = r.json()
        self._record(method, url, merged, status, j)
        if j.get("status") != "success":
            err = j.get("error", {})
            raise RuntimeError(err.get("message") or err.get("code") or "alldebrid error")
        return j.get("data", {})

    async def _get(self, path: str, **params):
        return await self._call(BASE, path, **params)

    async def list_links(self, force: bool = False) -> list[DebridLink]:
        self._reset_debug()
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
                        resolve_hint={
                            "k": "unlock",
                            "u": l["link"],
                            "del": {"t": "link", "link": l["link"]},
                        },
                    )
                )
        except Exception as exc:  # noqa: BLE001 — surfaced via `warnings`, not swallowed
            self.warnings.append(f"saved links: {type(exc).__name__}: {exc}")

        # Files inside completed ("Ready") magnets
        try:
            status = await self._call(BASE_V41, "/magnet/status")
            magnets = status.get("magnets", [])
            if isinstance(magnets, dict):
                magnets = list(magnets.values())
            by_id = {m["id"]: m for m in magnets}
            ready_ids = [m["id"] for m in magnets if m.get("statusCode") == _READY]

            files_by_magnet: dict[int, list[dict]] = {}
            for chunk in _chunks(ready_ids, _CHUNK):
                fdata = await self._get("/magnet/files", **{"id[]": chunk})
                for fm in fdata.get("magnets", []):
                    files_by_magnet[int(fm["id"])] = fm.get("files") or []

            for mid, files in files_by_magnet.items():
                m = by_id.get(mid, {})
                for leaf in _flatten_files(files):
                    out.append(
                        DebridLink(
                            provider=self.name,
                            name=leaf.get("n") or m.get("filename", ""),
                            size=int(leaf.get("s") or 0),
                            host="alldebrid",
                            kind="magnet",
                            added=unix_to_iso(m.get("completionDate") or m.get("uploadDate")),
                            direct_url=None,
                            # AllDebrid can only delete a whole magnet, not one
                            # file inside it -- deleting removes every sibling too.
                            resolve_hint={
                                "k": "unlock",
                                "u": leaf["l"],
                                "del": {"t": "magnet", "id": mid},
                            },
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"magnets: {type(exc).__name__}: {exc}")

        return out

    async def resolve(self, hint: dict) -> str:
        data = await self._get("/link/unlock", link=hint["u"])
        return data["link"]

    async def delete(self, hint: dict) -> None:
        d = hint.get("del") or {}
        if d.get("t") == "link":
            await self._get("/user/links/delete", link=d["link"])
        elif d.get("t") == "magnet" and d.get("id") is not None:
            await self._get("/magnet/delete", id=d["id"])
        else:
            raise ValueError("alldebrid: this link cannot be deleted")

    async def health(self) -> bool:
        try:
            await self._get("/user")
            return True
        except Exception:
            return False
