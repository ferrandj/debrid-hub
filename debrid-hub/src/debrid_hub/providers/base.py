from __future__ import annotations

import abc

import httpx

from ..models import DebridLink


class Provider(abc.ABC):
    """A debrid backend. Add a new service by subclassing this and registering it
    in aggregator.Aggregator._build()."""

    name: str = "base"
    # Optional operations this backend supports beyond list/resolve, e.g.
    # ("delete",). The UI/API use it to decide which management actions to offer.
    capabilities: tuple[str, ...] = ()

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @abc.abstractmethod
    async def list_links(self, force: bool = False) -> list[DebridLink]:
        """Return every downloadable item the account holds (metadata only, cheap).

        ``force`` is set when the user explicitly refreshes; providers that sit
        behind their own server-side cache should bypass it in that case so a
        just-deleted item doesn't linger.
        """

    @abc.abstractmethod
    async def resolve(self, hint: dict) -> str:
        """Turn a resolve_hint into a final direct download URL (may be metered)."""

    async def delete(self, hint: dict) -> None:
        """Delete the item behind a resolve_hint from the provider account.

        Granularity is whatever the provider API allows: some services delete a
        single link, others only the whole parent torrent/magnet (removing all of
        its files). Providers that support this set ``capabilities = ("delete",)``.
        """
        raise NotImplementedError(f"{self.name}: delete is not supported")

    async def health(self) -> bool:
        """Cheap credential check. Override per provider."""
        return True
