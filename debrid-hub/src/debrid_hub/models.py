from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class DebridLink:
    """A single downloadable item, normalized across every debrid provider.

    `direct_url` is set only when the provider already exposes a downloadable URL
    (e.g. Real-Debrid /downloads history). Otherwise the link must be resolved
    on demand via `resolve_hint`, which carries the provider-specific data needed
    to turn it into a direct URL (a locked link, or torrent/file ids).
    """

    provider: str
    name: str
    size: int
    host: str
    kind: str                      # download | torrent | webdl | usenet | magnet | saved
    added: Optional[str]           # ISO-8601 string or None
    direct_url: Optional[str]
    resolve_hint: dict = field(default_factory=dict)
    id: str = ""

    def compute_id(self) -> str:
        payload = {"p": self.provider, "h": self.resolve_hint}
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("resolve_hint", None)          # internal only, never sent to clients
        d["id"] = self.id or self.compute_id()
        d["resolvable"] = self.direct_url is None
        return d


def decode_id(token: str) -> dict:
    pad = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(token + pad)
    return json.loads(raw)
