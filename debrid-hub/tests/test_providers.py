from __future__ import annotations

import httpx
import pytest

from debrid_hub.providers.alldebrid import AllDebrid
from debrid_hub.providers.mock import Mock
from debrid_hub.providers.realdebrid import RealDebrid
from debrid_hub.providers.torbox import TorBox


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRealDebrid:
    """Fixture shapes confirmed against the real API (see PRODUCT.md)."""

    def _handler(self, *, torrents=None, torrent_info=None, downloads=None):
        torrents = torrents if torrents is not None else []
        downloads = downloads if downloads is not None else []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/rest/1.0/downloads":
                page = int(request.url.params.get("page", "1"))
                return httpx.Response(200 if downloads else 204, json=downloads if page == 1 else [])
            if path == "/rest/1.0/torrents":
                page = int(request.url.params.get("page", "1"))
                return httpx.Response(200, json=torrents if page == 1 else [])
            if path.startswith("/rest/1.0/torrents/info/"):
                tid = path.rsplit("/", 1)[-1]
                return httpx.Response(200, json=torrent_info.get(tid, {}))
            if path == "/rest/1.0/user":
                return httpx.Response(200, json={"id": 1})
            return httpx.Response(404, json={"error": "not found"})

        return handler

    async def test_list_links_includes_download_history(self):
        downloads = [{"id": "d1", "filename": "movie.mkv", "filesize": 100, "host": "1fichier", "generated": "2026-01-01", "download": "https://dl/movie.mkv"}]
        async with client_for(self._handler(downloads=downloads)) as client:
            rd = RealDebrid(client, "fake-token")
            links = await rd.list_links()
        assert len(links) == 1
        assert links[0].name == "movie.mkv"
        assert links[0].direct_url == "https://dl/movie.mkv"
        assert links[0].kind == "download"

    async def test_list_links_includes_ready_torrent_files_only(self):
        torrents = [
            {"id": "T1", "status": "downloaded", "filename": "Show", "added": "2026-01-01"},
            {"id": "T2", "status": "downloading", "filename": "NotReady", "added": "2026-01-01"},
        ]
        torrent_info = {
            "T1": {
                "id": "T1", "filename": "Show", "added": "2026-01-01",
                "files": [
                    {"id": 1, "path": "/Show.S01E01.mkv", "bytes": 900, "selected": 1},
                    {"id": 2, "path": "/sample.mkv", "bytes": 5, "selected": 0},
                ],
                "links": ["https://real-debrid.com/d/LOCKED1"],
            }
        }
        async with client_for(self._handler(torrents=torrents, torrent_info=torrent_info)) as client:
            rd = RealDebrid(client, "fake-token")
            links = await rd.list_links()
        assert len(links) == 1, "unselected file excluded, non-ready torrent skipped entirely"
        assert links[0].name == "Show.S01E01.mkv"
        assert links[0].kind == "torrent"
        assert links[0].resolve_hint["del"] == {"kind": "torrent", "id": "T1"}

    async def test_resolve_direct_url_needs_no_network(self):
        async with client_for(lambda r: httpx.Response(500)) as client:
            rd = RealDebrid(client, "fake-token")
            url = await rd.resolve({"k": "direct", "u": "https://already-direct.example/f.mkv"})
        assert url == "https://already-direct.example/f.mkv"

    async def test_resolve_restrict_calls_unrestrict_endpoint(self):
        def handler(request):
            if request.url.path == "/rest/1.0/unrestrict/link":
                return httpx.Response(200, json={"download": "https://resolved.example/f.mkv"})
            return httpx.Response(404)
        async with client_for(handler) as client:
            rd = RealDebrid(client, "fake-token")
            url = await rd.resolve({"k": "restrict", "u": "https://locked.example/f"})
        assert url == "https://resolved.example/f.mkv"

    async def test_delete_download_uses_downloads_endpoint(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(204)
        async with client_for(handler) as client:
            rd = RealDebrid(client, "fake-token")
            await rd.delete({"del": {"kind": "download", "id": "d1"}})
        assert calls == ["/rest/1.0/downloads/delete/d1"]

    async def test_delete_torrent_uses_torrents_endpoint(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(204)
        async with client_for(handler) as client:
            rd = RealDebrid(client, "fake-token")
            await rd.delete({"del": {"kind": "torrent", "id": "T1"}})
        assert calls == ["/rest/1.0/torrents/delete/T1"]

    async def test_delete_without_id_raises(self):
        async with client_for(lambda r: httpx.Response(500)) as client:
            rd = RealDebrid(client, "fake-token")
            with pytest.raises(ValueError):
                await rd.delete({"del": {}})

    async def test_debug_mode_records_calls_with_redacted_nothing_sensitive_in_params(self):
        # RD auth is a Bearer header, never a query param -- nothing to redact,
        # but debug_log should still populate when debug=True.
        async with client_for(self._handler(downloads=[])) as client:
            rd = RealDebrid(client, "fake-token")
            rd.debug = True
            await rd.list_links()
        assert len(rd.debug_log) >= 1
        assert all("fake-token" not in str(c) for c in rd.debug_log)


class TestAllDebrid:
    def _handler(self, *, links=None, magnets=None, files_by_magnet=None):
        links = links or []
        magnets = magnets or []
        files_by_magnet = files_by_magnet or {}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/v4/user/links":
                return httpx.Response(200, json={"status": "success", "data": {"links": links}})
            if path == "/v4.1/magnet/status":
                return httpx.Response(200, json={"status": "success", "data": {"magnets": magnets}})
            if path == "/v4/magnet/files":
                ids = request.url.params.get_list("id[]")
                out = [{"id": i, "files": files_by_magnet.get(int(i), [])} for i in ids]
                return httpx.Response(200, json={"status": "success", "data": {"magnets": out}})
            if path == "/v4/link/unlock":
                return httpx.Response(200, json={"status": "success", "data": {"link": "https://unlocked.example/f"}})
            if path == "/v4/magnet/delete":
                return httpx.Response(200, json={"status": "success", "data": {}})
            if path == "/v4/user/links/delete":
                return httpx.Response(200, json={"status": "success", "data": {}})
            if path == "/v4/user":
                return httpx.Response(200, json={"status": "success", "data": {}})
            return httpx.Response(404, json={"status": "error", "error": {"message": "not found"}})

        return handler

    async def test_saved_links_are_listed(self):
        links = [{"filename": "movie.mkv", "size": 100, "host": "1fichier", "date": 1700000000, "link": "https://ad.link/x"}]
        async with client_for(self._handler(links=links)) as client:
            ad = AllDebrid(client, "fake-key")
            out = await ad.list_links()
        assert len(out) == 1
        assert out[0].kind == "saved"
        assert out[0].resolve_hint["del"] == {"t": "link", "link": "https://ad.link/x"}

    async def test_only_ready_magnets_files_are_fetched(self):
        magnets = [
            {"id": 1, "filename": "Ready", "statusCode": 4, "completionDate": 1700000000},
            {"id": 2, "filename": "NotReady", "statusCode": 1},
        ]
        files_by_magnet = {1: [{"n": "Ready.mkv", "s": 500, "l": "https://ad.link/ready"}]}
        async with client_for(self._handler(magnets=magnets, files_by_magnet=files_by_magnet)) as client:
            ad = AllDebrid(client, "fake-key")
            out = await ad.list_links()
        assert len(out) == 1
        assert out[0].name == "Ready.mkv"
        assert out[0].resolve_hint["del"] == {"t": "magnet", "id": 1}

    async def test_nested_folder_files_are_flattened(self):
        magnets = [{"id": 1, "filename": "Pack", "statusCode": 4, "completionDate": 1700000000}]
        files_by_magnet = {1: [
            {"n": "Pack", "e": [
                {"n": "ep1.mkv", "s": 100, "l": "https://ad.link/1"},
                {"n": "ep2.mkv", "s": 200, "l": "https://ad.link/2"},
            ]},
        ]}
        async with client_for(self._handler(magnets=magnets, files_by_magnet=files_by_magnet)) as client:
            ad = AllDebrid(client, "fake-key")
            out = await ad.list_links()
        assert sorted(l.name for l in out) == ["ep1.mkv", "ep2.mkv"]

    async def test_magnet_status_failure_is_recorded_as_warning_not_swallowed(self):
        def handler(request):
            if request.url.path == "/v4/user/links":
                return httpx.Response(200, json={"status": "success", "data": {"links": []}})
            if request.url.path == "/v4.1/magnet/status":
                return httpx.Response(200, json={"status": "error", "error": {"code": "DISCONTINUED", "message": "gone"}})
            return httpx.Response(404)
        async with client_for(handler) as client:
            ad = AllDebrid(client, "fake-key")
            out = await ad.list_links()
        assert out == []
        assert any("magnets" in w for w in ad.warnings)
        assert any("gone" in w for w in ad.warnings)

    async def test_resolve_calls_unlock(self):
        async with client_for(self._handler()) as client:
            ad = AllDebrid(client, "fake-key")
            url = await ad.resolve({"u": "https://locked.example/x"})
        assert url == "https://unlocked.example/f"

    async def test_delete_link_vs_magnet_routes_differently(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"status": "success", "data": {}})
        async with client_for(handler) as client:
            ad = AllDebrid(client, "fake-key")
            await ad.delete({"del": {"t": "link", "link": "https://x"}})
            await ad.delete({"del": {"t": "magnet", "id": 5}})
        assert calls == ["/v4/user/links/delete", "/v4/magnet/delete"]

    async def test_delete_unknown_type_raises(self):
        async with client_for(self._handler()) as client:
            ad = AllDebrid(client, "fake-key")
            with pytest.raises(ValueError):
                await ad.delete({"del": {}})


class TestTorBox:
    def _handler(self, *, items_by_kind=None, delete_success=True):
        items_by_kind = items_by_kind or {}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            for kind, listpath in [("torrent", "/torrents/mylist"), ("webdl", "/webdl/mylist"), ("usenet", "/usenet/mylist")]:
                if path.endswith(listpath):
                    return httpx.Response(200, json={"success": True, "data": items_by_kind.get(kind, [])})
            if any(path.endswith(p) for p in ("/torrents/controltorrent", "/webdl/controlwebdownload", "/usenet/controlusenet")):
                return httpx.Response(200, json={"success": delete_success, "detail": "" if delete_success else "failed"})
            if path.endswith("/user/me"):
                return httpx.Response(200, json={"success": True, "data": {}})
            if path.endswith("/requestdl"):
                return httpx.Response(200, json={"success": True, "data": "https://tb.example/direct.mkv"})
            return httpx.Response(404, json={"success": False})

        return handler

    async def test_list_links_bypass_cache_reflects_force_flag(self):
        seen = []
        def handler(request):
            if "mylist" in request.url.path:
                seen.append(request.url.params.get("bypass_cache"))
            return httpx.Response(200, json={"success": True, "data": []})
        async with client_for(handler) as client:
            tb = TorBox(client, "fake-key")
            await tb.list_links(force=False)
            await tb.list_links(force=True)
        assert seen[:3] == ["false", "false", "false"]
        assert seen[3:] == ["true", "true", "true"]

    async def test_list_links_across_all_three_kinds(self):
        items_by_kind = {
            "torrent": [{"id": 1, "name": "T", "files": [{"id": 10, "name": "t.mkv", "size": 100}]}],
            "webdl": [{"id": 2, "name": "W", "files": [{"id": 20, "short_name": "w.mkv", "size": 200}]}],
            "usenet": [{"id": 3, "name": "U", "files": [{"id": 30, "name": "u.mkv", "size": 300}]}],
        }
        async with client_for(self._handler(items_by_kind=items_by_kind)) as client:
            tb = TorBox(client, "fake-key")
            out = await tb.list_links()
        assert {l.kind for l in out} == {"torrent", "webdl", "usenet"}
        assert len(out) == 3

    async def test_one_kind_failing_does_not_break_the_others(self):
        def handler(request):
            if request.url.path.endswith("/torrents/mylist"):
                return httpx.Response(500)
            if "mylist" in request.url.path:
                return httpx.Response(200, json={"success": True, "data": []})
            return httpx.Response(404)
        async with client_for(handler) as client:
            tb = TorBox(client, "fake-key")
            out = await tb.list_links()
        assert out == []
        assert any("torrent" in w for w in tb.warnings)

    async def test_resolve_calls_requestdl_with_correct_id_field(self):
        seen = {}
        def handler(request):
            if "requestdl" in request.url.path:
                seen.update(request.url.params)
                return httpx.Response(200, json={"success": True, "data": "https://direct.example/f"})
            return httpx.Response(404)
        async with client_for(handler) as client:
            tb = TorBox(client, "fake-key")
            url = await tb.resolve({"k": "webdl", "i": 42, "f": 7})
        assert url == "https://direct.example/f"
        assert seen["web_id"] == "42"

    async def test_delete_unknown_kind_raises(self):
        async with client_for(self._handler()) as client:
            tb = TorBox(client, "fake-key")
            with pytest.raises(ValueError):
                await tb.delete({"k": "not-a-kind", "i": 1})


class TestMock:
    async def test_list_links_returns_samples(self):
        async with httpx.AsyncClient() as client:
            m = Mock(client)
            out = await m.list_links()
        assert len(out) > 0
        assert any(l.kind == "torrent" for l in out)

    async def test_delete_removes_from_subsequent_listing(self):
        async with httpx.AsyncClient() as client:
            m = Mock(client)
            before = await m.list_links()
            target = next(l for l in before if "ubuntu" in l.name.lower())
            await m.delete(target.resolve_hint)
            after = await m.list_links()
        assert len(after) == len(before) - 1
        assert not any("ubuntu" in l.name.lower() for l in after)

    async def test_delete_without_url_raises(self):
        async with httpx.AsyncClient() as client:
            m = Mock(client)
            with pytest.raises(ValueError):
                await m.delete({})
