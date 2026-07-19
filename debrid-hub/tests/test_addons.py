from __future__ import annotations

import httpx
import pytest

from debrid_hub import addons


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestBaseUrl:
    def test_strips_manifest_json_suffix(self):
        assert addons.base_url("https://example.com/token/manifest.json") == "https://example.com/token"

    def test_strips_trailing_slash_before_checking_suffix(self):
        assert addons.base_url("https://example.com/token/manifest.json/") == "https://example.com/token"

    def test_leaves_url_without_manifest_suffix_alone(self):
        assert addons.base_url("https://example.com/token") == "https://example.com/token"


class TestFetchManifest:
    async def test_valid_manifest_returns_parsed_json(self):
        manifest = {"id": "x", "name": "Test", "resources": ["catalog"]}
        async with client_for(lambda r: httpx.Response(200, json=manifest)) as client:
            result = await addons.fetch_manifest(client, "https://example.com/manifest.json")
        assert result == manifest

    async def test_non_json_response_raises_addon_error(self):
        async with client_for(lambda r: httpx.Response(200, text="<html>not json</html>")) as client:
            with pytest.raises(addons.AddonError):
                await addons.fetch_manifest(client, "https://example.com/manifest.json")

    async def test_missing_resources_raises_addon_error(self):
        async with client_for(lambda r: httpx.Response(200, json={"id": "x"})) as client:
            with pytest.raises(addons.AddonError):
                await addons.fetch_manifest(client, "https://example.com/manifest.json")

    async def test_http_error_propagates(self):
        async with client_for(lambda r: httpx.Response(404)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await addons.fetch_manifest(client, "https://example.com/manifest.json")


class TestSummarizeManifest:
    def test_extracts_expected_fields(self):
        manifest = {
            "name": "Cinemeta", "description": "desc",
            "resources": ["catalog", "meta"],
            "types": ["movie", "series"],
            "catalogs": [{"type": "movie", "id": "top", "name": "Popular", "extra": [{"name": "search"}]}],
        }
        s = addons.summarize_manifest(manifest)
        assert s["name"] == "Cinemeta"
        assert s["resources"] == ["catalog", "meta"]
        assert s["catalogs"][0]["searchable"] is True

    def test_catalog_without_search_extra_is_not_searchable(self):
        manifest = {"name": "X", "resources": [], "catalogs": [{"type": "movie", "id": "a", "extra": [{"name": "genre"}]}]}
        s = addons.summarize_manifest(manifest)
        assert s["catalogs"][0]["searchable"] is False

    def test_falls_back_to_id_when_name_missing(self):
        manifest = {"id": "com.example.addon", "resources": []}
        assert addons.summarize_manifest(manifest)["name"] == "com.example.addon"

    def test_handles_resource_objects_not_just_strings(self):
        # some addons declare resources as {"name": "stream", "types": [...]} objects
        manifest = {"name": "X", "resources": [{"name": "stream", "types": ["movie"]}]}
        assert addons.summarize_manifest(manifest)["resources"] == ["stream"]


class TestFetchCatalog:
    async def test_basic_catalog_fetch(self):
        async with client_for(lambda r: httpx.Response(200, json={"metas": [{"id": "tt1", "name": "Movie"}]})) as client:
            items = await addons.fetch_catalog(client, "https://x.example", "movie", "top")
        assert items == [{"id": "tt1", "name": "Movie"}]

    async def test_search_param_is_url_encoded_on_the_wire(self):
        seen = {}
        def handler(request):
            seen["raw"] = bytes(request.url.raw_path).decode()
            seen["decoded"] = request.url.path
            return httpx.Response(200, json={"metas": []})
        async with client_for(handler) as client:
            await addons.fetch_catalog(client, "https://x.example", "movie", "top", search="Les Bronzés")
        assert "search=" in seen["decoded"]
        assert "Bronz" in seen["decoded"]  # server-visible, decoded form is readable
        assert "%20" in seen["raw"], "space must be percent-encoded on the wire"
        assert " " not in seen["raw"], "raw wire bytes must not contain a literal space"

    async def test_genre_and_skip_both_included(self):
        seen = {}
        def handler(request):
            seen["path"] = request.url.path
            return httpx.Response(200, json={"metas": []})
        async with client_for(handler) as client:
            await addons.fetch_catalog(client, "https://x.example", "movie", "top", genre="Comedy", skip=50)
        assert "genre=Comedy" in seen["path"]
        assert "skip=50" in seen["path"]

    async def test_missing_metas_key_returns_empty_list(self):
        async with client_for(lambda r: httpx.Response(200, json={})) as client:
            items = await addons.fetch_catalog(client, "https://x.example", "movie", "top")
        assert items == []


class TestFetchMeta:
    async def test_returns_meta_object(self):
        async with client_for(lambda r: httpx.Response(200, json={"meta": {"name": "Movie"}})) as client:
            meta = await addons.fetch_meta(client, "https://x.example", "movie", "tt1")
        assert meta == {"name": "Movie"}

    async def test_404_returns_none_not_an_exception(self):
        async with client_for(lambda r: httpx.Response(404)) as client:
            meta = await addons.fetch_meta(client, "https://x.example", "movie", "tt1")
        assert meta is None


class TestFetchStreams:
    async def test_returns_streams_list(self):
        async with client_for(lambda r: httpx.Response(200, json={"streams": [{"url": "https://x/y"}]})) as client:
            streams = await addons.fetch_streams(client, "https://x.example", "movie", "tt1")
        assert streams == [{"url": "https://x/y"}]

    async def test_404_returns_empty_list(self):
        async with client_for(lambda r: httpx.Response(404)) as client:
            streams = await addons.fetch_streams(client, "https://x.example", "movie", "tt1")
        assert streams == []


class TestTriggerStream:
    """Covers the AllDebrid-vs-TorBox bug investigation: a success response's
    body must never be read (streams can be 50+ GB), but a failure response's
    body must be read and its reason surfaced -- this is what used to make an
    addon-side failure indistinguishable from any other failure in the UI."""

    async def test_success_returns_status_and_no_detail_and_never_reads_body(self):
        read_body = {"called": False}
        async def raising_stream(*a, **kw):
            raise AssertionError("must not read a successful stream's body")

        def handler(request):
            return httpx.Response(200, headers={"content-type": "application/octet-stream"})
        async with client_for(handler) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/video.mkv")
        assert status == 200
        assert detail is None

    async def test_error_json_body_detail_is_extracted(self):
        async with client_for(lambda r: httpx.Response(404, json={"detail": "Résolution impossible"})) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/video.mkv")
        assert status == 404
        assert detail == "Résolution impossible"

    async def test_error_json_falls_back_to_error_or_message_keys(self):
        async with client_for(lambda r: httpx.Response(500, json={"error": "boom"})) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/video.mkv")
        assert detail == "boom"

    async def test_error_plain_text_body_is_used_as_detail(self):
        async with client_for(lambda r: httpx.Response(502, text="Bad Gateway")) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/video.mkv")
        assert detail == "Bad Gateway"

    async def test_detail_is_truncated_to_reasonable_length(self):
        async with client_for(lambda r: httpx.Response(400, text="x" * 10000)) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/video.mkv")
        assert len(detail) <= 500

    async def test_redirect_is_followed_before_status_is_read(self):
        def handler(request):
            if request.url.path == "/start":
                return httpx.Response(307, headers={"location": "/final"})
            return httpx.Response(200)
        async with client_for(handler) as client:
            status, detail = await addons.trigger_stream(client, "https://x.example/start")
        assert status == 200
