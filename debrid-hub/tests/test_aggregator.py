from __future__ import annotations

import pytest

from debrid_hub.aggregator import Aggregator, filter_sort
from debrid_hub.config import Settings
from debrid_hub.models import DebridLink
from debrid_hub.store import SecretStore


def link(**overrides):
    defaults = dict(
        provider="mock", name="Show.S01E01.mkv", size=100, host="mock",
        kind="torrent", added="2026-01-01", direct_url=None,
        resolve_hint={"k": "direct", "u": "x"},
    )
    defaults.update(overrides)
    return DebridLink(**defaults)


class TestFilterSort:
    def test_filter_by_provider(self):
        items = [link(provider="torbox"), link(provider="alldebrid")]
        assert [l.provider for l in filter_sort(items, provider="torbox")] == ["torbox"]

    def test_filter_by_kind(self):
        items = [link(kind="torrent"), link(kind="saved")]
        assert [l.kind for l in filter_sort(items, kind="saved")] == ["saved"]

    def test_search_matches_name_case_insensitively(self):
        items = [link(name="Breaking.Bad.S01E01.mkv"), link(name="Other.mkv")]
        result = filter_sort(items, search="breaking")
        assert len(result) == 1

    def test_search_matches_host_too(self):
        items = [link(name="a.mkv", host="realdebrid"), link(name="b.mkv", host="torbox")]
        result = filter_sort(items, search="torbox")
        assert len(result) == 1 and result[0].name == "b.mkv"

    def test_sort_by_size_ascending(self):
        items = [link(size=300), link(size=100), link(size=200)]
        assert [l.size for l in filter_sort(items, sort="size", order="asc")] == [100, 200, 300]

    def test_sort_by_size_descending(self):
        items = [link(size=300), link(size=100), link(size=200)]
        assert [l.size for l in filter_sort(items, sort="size", order="desc")] == [300, 200, 100]

    def test_sort_by_name_case_insensitive(self):
        items = [link(name="zebra.mkv"), link(name="Apple.mkv")]
        assert [l.name for l in filter_sort(items, sort="name")] == ["Apple.mkv", "zebra.mkv"]

    def test_unknown_sort_key_falls_back_to_name(self):
        items = [link(name="b.mkv"), link(name="a.mkv")]
        assert [l.name for l in filter_sort(items, sort="not-a-real-field")] == ["a.mkv", "b.mkv"]

    def test_combined_filter_and_search(self):
        items = [
            link(provider="torbox", name="match.mkv"),
            link(provider="torbox", name="nomatch.mkv"),
            link(provider="alldebrid", name="match.mkv"),
        ]
        result = filter_sort(items, provider="torbox", search="match")
        assert len(result) == 2
        assert all(l.provider == "torbox" for l in result)


class TestAggregatorProviderConstruction:
    def test_no_credentials_no_providers(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir))
        assert agg.provider_names == []

    def test_mock_flag_adds_mock_provider(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True))
        assert "mock" in agg.provider_names

    def test_env_var_credential_builds_provider(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, torbox_apikey="from-env"))
        assert "torbox" in agg.provider_names

    def test_stored_credential_builds_provider(self, data_dir):
        SecretStore(data_dir).set("realdebrid", "from-store")
        agg = Aggregator(Settings(data_dir=data_dir))
        assert "realdebrid" in agg.provider_names

    def test_stored_credential_overrides_env(self, data_dir):
        SecretStore(data_dir).set("torbox", "from-store")
        agg = Aggregator(Settings(data_dir=data_dir, torbox_apikey="from-env"))
        assert agg._providers["torbox"]._key == "from-store"

    def test_reload_picks_up_credential_written_out_of_band(self, data_dir):
        """This is exactly the gap the Load button/reload endpoint closes: a
        key written to the store after the Aggregator was built must stay
        invisible until reload() is called."""
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True))
        assert agg.provider_names == ["mock"]
        SecretStore(data_dir).set("torbox", "written-later")
        assert agg.provider_names == ["mock"], "must still be stale before reload()"
        agg.reload()
        assert "torbox" in agg.provider_names

    def test_delete_credential_removes_provider_falls_back_to_env(self, data_dir):
        SecretStore(data_dir).set("torbox", "stored-value")
        agg = Aggregator(Settings(data_dir=data_dir, torbox_apikey="env-value"))
        assert agg._providers["torbox"]._key == "stored-value"
        agg.delete_credential("torbox")
        assert agg._providers["torbox"]._key == "env-value"

    def test_broken_store_does_not_crash_startup(self, data_dir):
        # wrong master key => decrypt failure inside _build(), must be caught
        SecretStore(data_dir, master_key="key-a").set("torbox", "x")
        agg = Aggregator(Settings(data_dir=data_dir, secret_key="key-b"))
        assert agg.store_error != ""
        assert agg.provider_names == []  # degrades gracefully, doesn't raise


class TestAggregatorListLinks:
    async def test_list_links_from_mock_provider(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True))
        try:
            links = await agg.list_links()
            assert len(links) > 0
            assert all(l.id for l in links), "ids must be computed during list_links"
        finally:
            await agg.aclose()

    async def test_cache_is_reused_within_ttl(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True, cache_ttl=3600))
        try:
            first = await agg.list_links()
            second = await agg.list_links()  # no force -> cached
            assert first is second
        finally:
            await agg.aclose()

    async def test_force_bypasses_cache(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True, cache_ttl=3600))
        try:
            first = await agg.list_links()
            second = await agg.list_links(force=True)
            assert first is not second
        finally:
            await agg.aclose()

    async def test_delete_invalidates_cache(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True, cache_ttl=3600))
        try:
            links = await agg.list_links()
            target = links[0]
            await agg.delete(target.id)
            assert agg._cache is None
        finally:
            await agg.aclose()

    async def test_resolve_unknown_provider_in_id_raises(self, data_dir):
        agg = Aggregator(Settings(data_dir=data_dir, enable_mock=True))
        try:
            fake_id = DebridLink(
                provider="not-configured", name="x", size=1, host="x", kind="torrent",
                added=None, direct_url=None, resolve_hint={},
            ).compute_id()
            with pytest.raises(KeyError):
                await agg.resolve(fake_id)
        finally:
            await agg.aclose()
