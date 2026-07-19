from __future__ import annotations

import abc
import json as _json

import httpx

from ..models import DebridLink

_SECRET_PARAM_NAMES = {"apikey", "token", "authorization", "key"}


class Provider(abc.ABC):
    """A debrid backend. Add a new service by subclassing this and registering it
    in aggregator.Aggregator._build()."""

    name: str = "base"
    # Optional operations this backend supports beyond list/resolve, e.g.
    # ("delete",). The UI/API use it to decide which management actions to offer.
    capabilities: tuple[str, ...] = ()

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.debug: bool = False        # when True, _record() captures every call
        self.debug_log: list[dict] = []
        # Non-fatal failures from the last list_links() (e.g. one section of a
        # multi-part listing broke while others succeeded). Surfaced by the
        # aggregator instead of being silently swallowed.
        self.warnings: list[str] = []

    def _reset_debug(self) -> None:
        """Call at the top of list_links() so stale entries from a previous
        call don't linger or leak into the next debug snapshot."""
        self.debug_log = []
        self.warnings = []

    def _record(self, method: str, url: str, params: dict | None, status, body) -> None:
        """Record one outbound HTTP call for `debug=true` inspection. No-op
        unless ``self.debug`` is set. Secret-looking param values are redacted;
        auth carried in headers (Bearer tokens) is never touched here."""
        if not self.debug:
            return
        redacted = {
            k: ("***" if k.lower() in _SECRET_PARAM_NAMES else v)
            for k, v in (params or {}).items()
        }
        if isinstance(body, (dict, list)):
            body = _json.dumps(body)[:4000]
        elif isinstance(body, str):
            body = body[:4000]
        self.debug_log.append(
            {"method": method, "url": url, "params": redacted, "status": status, "body": body}
        )

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
