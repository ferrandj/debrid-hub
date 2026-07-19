from __future__ import annotations

import base64
import json

import httpx
import pytest

from debrid_hub.discover import DiscoverHub


CINEMETA = "https://cinemeta.example/manifest.json"
LUMIO = "https://lumio.example/TOKEN/manifest.json"


def route(rules: dict[str, dict | list]):
    """rules: {path_suffix: json_body}"""
    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, body in rules.items():
            if request.url.path.endswith(suffix) or (request.url.host + request.url.path).endswith(suffix):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "unhandled: " + str(request.url)})
    return handler


@pytest.fixture
def hub(settings, monkeypatch):
    h = DiscoverHub(settings)
    return h


class TestAddonManagement:
    async def test_add_addon_stores_encrypted_and_returns_summary(self, hub, monkeypatch):
        manifest = {"id": "x", "name": "Cinemeta", "resources": ["catalog", "meta"], "catalogs": []}
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(route({"manifest.json": manifest})))
        result = await hub.add_addon(CINEMETA)
        assert result["name"] == "Cinemeta"
        assert "url" not in result

    async def test_list_addons_never_includes_url(self, hub):
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(
            route({"manifest.json": {"id": "x", "name": "Cinemeta", "resources": ["catalog"], "catalogs": []}})))
        await hub.add_addon(CINEMETA)
        listed = hub.list_addons()
        assert len(listed) == 1
        assert "url" not in listed[0]

    async def test_remove_addon(self, hub):
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(
            route({"manifest.json": {"id": "x", "name": "X", "resources": ["catalog"], "catalogs": []}})))
        result = await hub.add_addon(CINEMETA)
        hub.remove_addon(result["id"])
        assert hub.list_addons() == []

    async def test_reupserting_same_url_does_not_duplicate(self, hub):
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(
            route({"manifest.json": {"id": "x", "name": "X", "resources": ["catalog"], "catalogs": []}})))
        await hub.add_addon(CINEMETA)
        await hub.add_addon(CINEMETA)
        assert len(hub.list_addons()) == 1


class TestCatalogSections:
    async def test_enumerates_addon_catalog_pairs(self, hub):
        manifest = {
            "id": "x", "name": "Streaming Catalogs", "resources": ["catalog"],
            "catalogs": [{"type": "movie", "id": "nfx", "name": "Netflix"}, {"type": "movie", "id": "hlu", "name": "Hulu"}],
        }
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(route({"manifest.json": manifest})))
        await hub.add_addon(CINEMETA)
        sections = hub.catalog_sections()
        names = {s["name"] for s in sections}
        assert names == {"Netflix", "Hulu"}
        assert all(s["addon_name"] == "Streaming Catalogs" for s in sections)


class TestSearch:
    async def test_fans_out_to_searchable_catalogs_only(self, hub):
        manifest = {
            "id": "x", "name": "Cinemeta", "resources": ["catalog"],
            "catalogs": [
                {"type": "movie", "id": "top", "name": "Popular", "extra": [{"name": "search"}]},
                {"type": "movie", "id": "new", "name": "New"},  # no search support
            ],
        }
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            if "/catalog/movie/top/" in request.url.path:
                return httpx.Response(200, json={"metas": [{"id": "tt1", "name": "Found"}]})
            return httpx.Response(200, json={"metas": []})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon(CINEMETA)
        results = await hub.search("query")
        assert len(results) == 1
        assert results[0]["name"] == "Found"
        assert not any("/catalog/movie/new" in c for c in calls), "non-searchable catalog must not be queried"

    async def test_dedupes_across_addons_first_hit_wins(self, hub):
        m1 = {"id": "a1", "name": "A1", "resources": ["catalog"],
              "catalogs": [{"type": "movie", "id": "c", "extra": [{"name": "search"}]}]}
        m2 = {"id": "a2", "name": "A2", "resources": ["catalog"],
              "catalogs": [{"type": "movie", "id": "c", "extra": [{"name": "search"}]}]}

        def handler(request):
            host = request.url.host
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=m1 if "a1" in host else m2)
            name = "From A1" if "a1" in host else "From A2"
            return httpx.Response(200, json={"metas": [{"id": "tt1", "name": name}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon("https://a1.example/manifest.json")
        await hub.add_addon("https://a2.example/manifest.json")
        results = await hub.search("query")
        assert len(results) == 1, "same id from two addons must collapse to one result"

    async def test_one_addon_failing_does_not_break_search(self, hub):
        m1 = {"id": "a1", "name": "Broken", "resources": ["catalog"],
              "catalogs": [{"type": "movie", "id": "c", "extra": [{"name": "search"}]}]}
        m2 = {"id": "a2", "name": "Working", "resources": ["catalog"],
              "catalogs": [{"type": "movie", "id": "c", "extra": [{"name": "search"}]}]}

        def handler(request):
            host = request.url.host
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=m1 if "a1" in host else m2)
            if "a1" in host:
                return httpx.Response(500)
            return httpx.Response(200, json={"metas": [{"id": "tt2", "name": "Survived"}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon("https://a1.example/manifest.json")
        await hub.add_addon("https://a2.example/manifest.json")
        results = await hub.search("query")
        assert len(results) == 1
        assert results[0]["name"] == "Survived"

    async def test_no_addons_returns_empty_list_not_error(self, hub):
        assert await hub.search("query") == []


class TestMeta:
    async def test_merges_fields_across_addons_first_set_wins(self, hub):
        m1 = {"id": "a1", "name": "Cinemeta", "resources": ["meta"], "catalogs": []}
        m2 = {"id": "a2", "name": "AIOMetadata", "resources": ["meta"], "catalogs": []}

        def handler(request):
            host = request.url.host
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=m1 if "a1" in host else m2)
            if "a1" in host:
                return httpx.Response(200, json={"meta": {"name": "Movie", "description": ""}})
            return httpx.Response(200, json={"meta": {"name": "Movie (should not override)", "description": "Full synopsis", "cast": ["Actor"]}})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon("https://a1.example/manifest.json")
        await hub.add_addon("https://a2.example/manifest.json")
        merged = await hub.meta("movie", "tt1")
        assert merged["name"] == "Movie", "first addon's non-empty field wins"
        assert merged["description"] == "Full synopsis", "second addon fills the gap first left empty"
        assert merged["cast"] == ["Actor"]

    async def test_returns_none_when_no_addon_has_meta_resource(self, hub):
        m1 = {"id": "a1", "name": "StreamOnly", "resources": ["stream"], "catalogs": []}
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(route({"manifest.json": m1})))
        await hub.add_addon(LUMIO)
        assert await hub.meta("movie", "tt1") is None


class TestStreams:
    async def test_streams_never_expose_raw_url(self, hub):
        manifest = {"id": "x", "name": "Lumio", "resources": ["stream"], "catalogs": []}
        def handler(request):
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            return httpx.Response(200, json={"streams": [{"name": "S1", "url": "https://lumio.example/secret-token/playback/xyz"}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon(LUMIO)
        streams = await hub.streams("movie", "tt1")
        assert len(streams) == 1
        assert "url" not in streams[0]
        assert "secret-token" not in json.dumps(streams[0])

    async def test_streams_without_url_are_skipped(self, hub):
        manifest = {"id": "x", "name": "Lumio", "resources": ["stream"], "catalogs": []}
        def handler(request):
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            return httpx.Response(200, json={"streams": [{"name": "magnet-only", "infoHash": "abc"}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon(LUMIO)
        assert await hub.streams("movie", "tt1") == []


class TestTriggerSecurity:
    """The core hardening: a stream token must not let a caller make this
    server fetch an arbitrary attacker-chosen host."""

    async def test_trigger_fetches_the_real_url_for_a_valid_token(self, hub):
        manifest = {"id": "x", "name": "Lumio", "resources": ["stream"], "catalogs": []}
        fetched = []
        def handler(request):
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            if "playback" in request.url.path:
                fetched.append(str(request.url))
                return httpx.Response(200)
            return httpx.Response(200, json={"streams": [{"name": "S1", "url": "https://lumio.example/x/playback/token"}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon(LUMIO)
        streams = await hub.streams("movie", "tt1")
        status, detail = await hub.trigger(streams[0]["token"])
        assert status == 200
        assert len(fetched) == 1

    async def test_forged_token_with_mismatched_host_is_rejected(self, hub):
        manifest = {"id": "x", "name": "Lumio", "resources": ["stream"], "catalogs": []}
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(route({"manifest.json": manifest})))
        addon = await hub.add_addon(LUMIO)
        forged = base64.urlsafe_b64encode(
            json.dumps({"a": addon["id"], "u": "https://evil.example.com/steal-data"}).encode()
        ).decode().rstrip("=")
        with pytest.raises(ValueError, match="host"):
            await hub.trigger(forged)

    async def test_token_referencing_unknown_addon_is_rejected(self, hub):
        forged = base64.urlsafe_b64encode(
            json.dumps({"a": "nonexistent-addon-id", "u": "https://anywhere.example/x"}).encode()
        ).decode().rstrip("=")
        with pytest.raises(KeyError):
            await hub.trigger(forged)

    async def test_trigger_surfaces_addon_failure_detail(self, hub):
        manifest = {"id": "x", "name": "Lumio", "resources": ["stream"], "catalogs": []}
        def handler(request):
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            if "playback" in request.url.path:
                return httpx.Response(404, json={"detail": "Résolution impossible"})
            return httpx.Response(200, json={"streams": [{"name": "S1", "url": "https://lumio.example/x/playback/token"}]})
        hub._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await hub.add_addon(LUMIO)
        streams = await hub.streams("movie", "tt1")
        status, detail = await hub.trigger(streams[0]["token"])
        assert status == 404
        assert detail == "Résolution impossible"
