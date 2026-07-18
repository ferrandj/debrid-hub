from __future__ import annotations

from ..models import DebridLink
from .base import Provider

_SAMPLES = [
    ("ubuntu-24.04.2-desktop-amd64.iso", 4_900_000_000, "download", "linuxtracker"),
    ("Big.Buck.Bunny.2160p.HDR.mkv", 1_355_000_000, "torrent", "mock"),
    ("blender-4.2-portable.zip", 312_000_000, "webdl", "download.blender.org"),
    ("debian-live-12.6.0-amd64.iso", 3_100_000_000, "torrent", "mock"),
    ("photos-backup-2025.tar", 8_800_000_000, "usenet", "mock"),
]


class Mock(Provider):
    """Fake provider so the app is fully demoable/testable without any API keys.
    Enable with DEBRID_HUB_MOCK=1."""

    name = "mock"

    async def list_links(self) -> list[DebridLink]:
        out: list[DebridLink] = []
        for i, (name, size, kind, host) in enumerate(_SAMPLES):
            url = f"https://example.com/{i}/{name}"
            out.append(
                DebridLink(
                    provider=self.name,
                    name=name,
                    size=size,
                    host=host,
                    kind=kind,
                    added=f"2026-01-{i + 1:02d}T12:00:00+00:00",
                    direct_url=url,
                    resolve_hint={"k": "direct", "u": url},
                )
            )
        return out

    async def resolve(self, hint: dict) -> str:
        return hint["u"]

    async def health(self) -> bool:
        return True
