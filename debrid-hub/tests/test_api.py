from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from debrid_hub.api import create_app
from debrid_hub.config import Settings
from debrid_hub.store import SecretStore


def app_client(**settings_kwargs):
    settings = Settings(**settings_kwargs)
    return TestClient(app=create_app(settings))


class TestAuth:
    def test_open_when_no_api_key_configured(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            assert client.get("/api/providers").status_code == 200

    def test_401_without_bearer_when_api_key_configured(self, data_dir):
        with app_client(data_dir=data_dir, api_key="secret123") as client:
            assert client.get("/api/providers").status_code == 401

    def test_401_with_wrong_bearer(self, data_dir):
        with app_client(data_dir=data_dir, api_key="secret123") as client:
            r = client.get("/api/providers", headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 401

    def test_200_with_correct_bearer(self, data_dir):
        with app_client(data_dir=data_dir, api_key="secret123") as client:
            r = client.get("/api/providers", headers={"Authorization": "Bearer secret123"})
            assert r.status_code == 200

    def test_health_never_requires_auth(self, data_dir):
        with app_client(data_dir=data_dir, api_key="secret123") as client:
            assert client.get("/health").status_code == 200


class TestProvidersAndLinks:
    def test_providers_lists_mock_with_capabilities(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            body = client.get("/api/providers").json()
        names = [p["name"] for p in body["providers"]]
        assert "mock" in names
        mock = next(p for p in body["providers"] if p["name"] == "mock")
        assert "delete" in mock["capabilities"]

    def test_links_returns_normalized_shape(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            body = client.get("/api/links").json()
        assert body["count"] > 0
        first = body["links"][0]
        assert set(["provider", "name", "size", "host", "kind", "id", "resolvable"]) <= set(first)
        assert "resolve_hint" not in first

    def test_links_search_filters(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            body = client.get("/api/links", params={"search": "ubuntu"}).json()
        assert all("ubuntu" in l["name"].lower() for l in body["links"])

    def test_links_debug_true_includes_debug_key(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            body = client.get("/api/links", params={"debug": "true"}).json()
        assert "debug" in body

    def test_index_page_serves_html(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<title>" in r.text


class TestResolveAndDelete:
    def test_resolve_known_mock_link(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            link_id = client.get("/api/links").json()["links"][0]["id"]
            body = client.post("/api/resolve", json={"id": link_id}).json()
        assert "url" in body["resolved"][link_id]

    def test_resolve_requires_id_or_ids(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            r = client.post("/api/resolve", json={})
        assert r.status_code == 400

    def test_delete_mock_link_removes_it_from_next_listing(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            before = client.get("/api/links").json()
            link_id = before["links"][0]["id"]
            del_body = client.post("/api/delete", json={"id": link_id}).json()
            assert del_body["deleted"][link_id]["ok"] is True
            after = client.get("/api/links", params={"refresh": "true"}).json()
        assert after["count"] == before["count"] - 1

    def test_delete_requires_id_or_ids(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            r = client.post("/api/delete", json={})
        assert r.status_code == 400


class TestConfig:
    def test_get_config_never_returns_key_values(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            client.put("/api/config", json={"torbox": "super-secret-value"})
            body = client.get("/api/config").json()
        assert "super-secret-value" not in str(body)

    def test_put_config_with_no_fields_is_400(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.put("/api/config", json={})
        assert r.status_code == 400

    def test_delete_unknown_provider_is_404(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.delete("/api/config/not-a-real-provider")
        assert r.status_code == 404

    def test_reload_picks_up_key_written_directly_to_store(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            before = client.get("/api/providers").json()
            assert "torbox" not in [p["name"] for p in before["providers"]]
            SecretStore(data_dir).set("torbox", "written-out-of-band")
            still_stale = client.get("/api/providers").json()
            assert "torbox" not in [p["name"] for p in still_stale["providers"]]
            client.post("/api/config/reload")
            after = client.get("/api/providers").json()
        assert "torbox" in [p["name"] for p in after["providers"]]


class TestWatchFolder:
    def test_status_disabled_by_default(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            body = client.get("/api/watchfolder").json()
        assert body == {"enabled": False, "cleanup_minutes": 0}

    def test_status_enabled_when_configured(self, data_dir, tmp_path):
        watch_dir = str(tmp_path / "watch")
        with app_client(data_dir=data_dir, watch_dir=watch_dir, watch_cleanup_minutes=60) as client:
            body = client.get("/api/watchfolder").json()
        assert body == {"enabled": True, "cleanup_minutes": 60}

    def test_drop_without_configured_folder_is_400(self, data_dir):
        with app_client(data_dir=data_dir, enable_mock=True) as client:
            link_id = client.get("/api/links").json()["links"][0]["id"]
            r = client.post("/api/watchfolder/drop", json={"id": link_id})
        assert r.status_code == 400

    def test_drop_requires_id_or_ids(self, data_dir, tmp_path):
        with app_client(data_dir=data_dir, enable_mock=True, watch_dir=str(tmp_path)) as client:
            r = client.post("/api/watchfolder/drop", json={})
        assert r.status_code == 400

    def test_drop_writes_file_with_resolved_urls(self, data_dir, tmp_path):
        watch_dir = tmp_path / "watch"
        with app_client(data_dir=data_dir, enable_mock=True, watch_dir=str(watch_dir)) as client:
            links = client.get("/api/links").json()["links"]
            ids = [l["id"] for l in links[:2]]
            body = client.post("/api/watchfolder/drop", json={"ids": ids, "name": "My Batch"}).json()
        assert body["ok"] is True
        assert body["written"] == 2
        files = list(watch_dir.iterdir())
        assert len(files) == 1
        assert files[0].name.startswith("My_Batch_")
        assert files[0].suffix == ".crawljob"
        content = files[0].read_text()
        assert content.count("deepAnalyseEnabled=true") == 2
        assert content.count("text=") == 2

    def test_drop_defaults_filename_when_no_name_given(self, data_dir, tmp_path):
        watch_dir = tmp_path / "watch"
        with app_client(data_dir=data_dir, enable_mock=True, watch_dir=str(watch_dir)) as client:
            link_id = client.get("/api/links").json()["links"][0]["id"]
            body = client.post("/api/watchfolder/drop", json={"id": link_id}).json()
        assert body["ok"] is True
        assert list(watch_dir.iterdir())[0].name.startswith("download_")

    def test_requires_auth_when_configured(self, data_dir, tmp_path):
        with app_client(data_dir=data_dir, api_key="secret123", watch_dir=str(tmp_path)) as client:
            assert client.get("/api/watchfolder").status_code == 401
            assert client.post("/api/watchfolder/drop", json={"id": "x"}).status_code == 401


class TestAddons:
    def _inject_manifest(self, client, manifest):
        """Route the DiscoverHub's internal client through a MockTransport
        that always serves this manifest -- avoids hitting real addons in
        the API-layer test suite (business logic is covered by
        tests/test_discover.py against real-shaped fixtures already)."""
        def handler(request):
            return httpx.Response(200, json=manifest)
        client.app.state.discover._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_add_list_remove_addon(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            self._inject_manifest(client, {"id": "x", "name": "Test Addon", "resources": ["catalog"], "catalogs": []})
            add_resp = client.post("/api/addons", json={"url": "https://example.com/manifest.json"})
            assert add_resp.status_code == 200
            addon_id = add_resp.json()["addon"]["id"]

            listed = client.get("/api/addons").json()["addons"]
            assert len(listed) == 1
            assert "url" not in listed[0]

            del_resp = client.delete(f"/api/addons/{addon_id}")
            assert del_resp.status_code == 200
            assert client.get("/api/addons").json()["addons"] == []

    def test_add_invalid_manifest_is_400(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            def handler(request):
                return httpx.Response(200, text="<html>not an addon</html>")
            client.app.state.discover._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            r = client.post("/api/addons", json={"url": "https://example.com/manifest.json"})
        assert r.status_code == 400


class TestDiscoverEndpoints:
    def _setup_addon(self, client, manifest, api_responses):
        def handler(request):
            if request.url.path.endswith("manifest.json"):
                return httpx.Response(200, json=manifest)
            for suffix, body in api_responses.items():
                if suffix in request.url.path:
                    return httpx.Response(200, json=body)
            return httpx.Response(404, json={"error": "unhandled"})
        client.app.state.discover._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client.post("/api/addons", json={"url": "https://example.com/manifest.json"}).json()["addon"]

    def test_catalogs_endpoint(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["catalog"],
                        "catalogs": [{"type": "movie", "id": "top", "name": "Popular"}]}
            self._setup_addon(client, manifest, {})
            body = client.get("/api/discover/catalogs").json()
        assert len(body["sections"]) == 1
        assert body["sections"][0]["name"] == "Popular"

    def test_catalog_browse_endpoint(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["catalog"],
                        "catalogs": [{"type": "movie", "id": "top", "name": "Popular"}]}
            addon = self._setup_addon(client, manifest, {"/catalog/": {"metas": [{"id": "tt1", "name": "Movie"}]}})
            body = client.get("/api/discover/catalog", params={"addon": addon["id"], "type": "movie", "catalog": "top"}).json()
        assert body["items"][0]["name"] == "Movie"

    def test_catalog_browse_unknown_addon_is_404(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.get("/api/discover/catalog", params={"addon": "nope", "type": "movie", "catalog": "top"})
        assert r.status_code == 404

    def test_search_endpoint(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["catalog"],
                        "catalogs": [{"type": "movie", "id": "top", "extra": [{"name": "search"}]}]}
            self._setup_addon(client, manifest, {"/catalog/": {"metas": [{"id": "tt1", "name": "Found"}]}})
            body = client.get("/api/discover/search", params={"q": "test"}).json()
        assert body["items"][0]["name"] == "Found"

    def test_search_requires_q(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.get("/api/discover/search", params={"q": ""})
        assert r.status_code == 400

    def test_meta_endpoint(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["meta"], "catalogs": []}
            self._setup_addon(client, manifest, {"/meta/": {"meta": {"name": "Movie Title"}}})
            body = client.get("/api/discover/meta", params={"type": "movie", "id": "tt1"}).json()
        assert body["meta"]["name"] == "Movie Title"

    def test_meta_404_when_nothing_found(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.get("/api/discover/meta", params={"type": "movie", "id": "tt1"})
        assert r.status_code == 404

    def test_streams_endpoint_tokenizes_url(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["stream"], "catalogs": []}
            self._setup_addon(client, manifest, {"/stream/": {"streams": [{"name": "S1", "url": "https://example.com/playback/secret"}]}})
            body = client.get("/api/discover/streams", params={"type": "movie", "id": "tt1"}).json()
        assert "url" not in body["streams"][0]
        assert "secret" not in str(body)
        assert body["streams"][0]["token"]

    def test_add_endpoint_success(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            manifest = {"id": "x", "name": "Test", "resources": ["stream"], "catalogs": []}
            self._setup_addon(client, manifest, {
                "/stream/": {"streams": [{"name": "S1", "url": "https://example.com/playback/secret"}]},
                "/playback/": None,  # handled below via status override
            })
            # override handler to give playback a clean 200
            def handler(request):
                if request.url.path.endswith("manifest.json"):
                    return httpx.Response(200, json=manifest)
                if "/stream/" in request.url.path:
                    return httpx.Response(200, json={"streams": [{"name": "S1", "url": "https://example.com/playback/secret"}]})
                if "/playback/" in request.url.path:
                    return httpx.Response(200)
                return httpx.Response(404)
            client.app.state.discover._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            streams = client.get("/api/discover/streams", params={"type": "movie", "id": "tt1"}).json()["streams"]
            body = client.post("/api/discover/add", json={"token": streams[0]["token"]}).json()
        assert body["ok"] is True
        assert body["status"] == 200

    def test_add_endpoint_surfaces_failure_detail(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            def handler(request):
                if request.url.path.endswith("manifest.json"):
                    return httpx.Response(200, json={"id": "x", "name": "Test", "resources": ["stream"], "catalogs": []})
                if "/stream/" in request.url.path:
                    return httpx.Response(200, json={"streams": [{"name": "S1", "url": "https://example.com/playback/secret"}]})
                if "/playback/" in request.url.path:
                    return httpx.Response(404, json={"detail": "Résolution impossible"})
                return httpx.Response(404)
            client.app.state.discover._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            client.post("/api/addons", json={"url": "https://example.com/manifest.json"})
            streams = client.get("/api/discover/streams", params={"type": "movie", "id": "tt1"}).json()["streams"]
            body = client.post("/api/discover/add", json={"token": streams[0]["token"]}).json()
        assert body["ok"] is False
        assert body["status"] == 404
        assert body["detail"] == "Résolution impossible"

    def test_add_endpoint_rejects_forged_token(self, data_dir):
        import base64, json as _json
        with app_client(data_dir=data_dir) as client:
            forged = base64.urlsafe_b64encode(_json.dumps({"a": "nope", "u": "https://evil.example/x"}).encode()).decode().rstrip("=")
            r = client.post("/api/discover/add", json={"token": forged})
        assert r.status_code == 400


class TestFavoritesEndpoints:
    def test_list_empty_by_default(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            body = client.get("/api/favorites").json()
        assert body["favorites"] == []

    def test_add_then_list(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            r = client.post("/api/favorites", json={"type": "movie", "id": "tt1", "name": "Test Movie", "poster": "https://x/1.jpg", "year": "2020"})
            assert r.status_code == 200
            assert r.json()["favorite"]["name"] == "Test Movie"
            body = client.get("/api/favorites").json()
        assert len(body["favorites"]) == 1
        assert body["favorites"][0]["id"] == "tt1"

    def test_remove(self, data_dir):
        with app_client(data_dir=data_dir) as client:
            client.post("/api/favorites", json={"type": "movie", "id": "tt1", "name": "Test"})
            r = client.delete("/api/favorites", params={"type": "movie", "id": "tt1"})
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            body = client.get("/api/favorites").json()
        assert body["favorites"] == []

    def test_requires_auth_when_configured(self, data_dir):
        with app_client(data_dir=data_dir, api_key="secret123") as client:
            assert client.get("/api/favorites").status_code == 401
            assert client.post("/api/favorites", json={"type": "movie", "id": "tt1"}).status_code == 401
