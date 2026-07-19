from __future__ import annotations

from ..models import DebridLink
from .base import Provider

# A mix of standalone files and multi-season TV series so grouping,
# resolving and deleting can all be exercised without any real API keys.
_SAMPLES: list[tuple[str, int, str, str]] = [
    ("ubuntu-24.04.2-desktop-amd64.iso", 4_900_000_000, "download", "linuxtracker"),
    ("blender-4.2-portable.zip", 312_000_000, "webdl", "download.blender.org"),
    ("photos-backup-2025.tar", 8_800_000_000, "usenet", "mock"),
    ("Big.Buck.Bunny.2160p.HDR.mkv", 1_355_000_000, "torrent", "mock"),
]


def _series(title: str, seasons: dict[int, int], size: int, host: str = "mock"):
    """Expand a show into one sample per episode: {season: episode_count}."""
    out: list[tuple[str, int, str, str]] = []
    for season, episodes in seasons.items():
        for ep in range(1, episodes + 1):
            name = f"{title}.S{season:02d}E{ep:02d}.1080p.WEB-DL.mkv"
            out.append((name, size, "torrent", host))
    return out


_SAMPLES += _series("Pioneer.One", {1: 6, 2: 4}, 900_000_000)
_SAMPLES += _series("Sintel.Chronicles", {1: 8}, 1_100_000_000)
_SAMPLES += _series("Cosmos.Lab", {1: 3, 2: 3, 3: 2}, 780_000_000)


class Mock(Provider):
    """Fake provider so the app is fully demoable/testable without any API keys.
    Enable with DEBRID_HUB_MOCK=1. Deletes are honoured in-memory for the life of
    the process, so the UI's delete flow can be tried end to end safely."""

    name = "mock"
    capabilities = ("delete",)

    def __init__(self, client) -> None:
        super().__init__(client)
        self._deleted: set[str] = set()

    async def list_links(self, force: bool = False) -> list[DebridLink]:
        out: list[DebridLink] = []
        for i, (name, size, kind, host) in enumerate(_SAMPLES):
            url = f"https://example.com/{i}/{name}"
            if url in self._deleted:
                continue
            out.append(
                DebridLink(
                    provider=self.name,
                    name=name,
                    size=size,
                    host=host,
                    kind=kind,
                    added=f"2026-01-{(i % 28) + 1:02d}T12:00:00+00:00",
                    direct_url=url,
                    resolve_hint={"k": "direct", "u": url, "del": {"u": url}},
                )
            )
        return out

    async def resolve(self, hint: dict) -> str:
        return hint["u"]

    async def delete(self, hint: dict) -> None:
        url = (hint.get("del") or {}).get("u") or hint.get("u")
        if not url:
            raise ValueError("mock: nothing to delete")
        self._deleted.add(url)

    async def health(self) -> bool:
        return True
