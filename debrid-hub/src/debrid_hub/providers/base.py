from __future__ import annotations

import abc

import httpx

from ..models import DebridLink


class Provider(abc.ABC):
    """A debrid backend. Add a new service by subclassing this and registering it
    in aggregator.Aggregator._build()."""

    name: str = "base"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @abc.abstractmethod
    async def list_links(self) -> list[DebridLink]:
        """Return every downloadable item the account holds (metadata only, cheap)."""

    @abc.abstractmethod
    async def resolve(self, hint: dict) -> str:
        """Turn a resolve_hint into a final direct download URL (may be metered)."""

    async def health(self) -> bool:
        """Cheap credential check. Override per provider."""
        return True
