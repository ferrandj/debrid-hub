from __future__ import annotations

import os

import pytest

from debrid_hub.config import Settings
from debrid_hub.store import AddonStore, FavoritesStore, SecretStore, credential_status


class TestSecretStore:
    def test_set_and_load(self, data_dir):
        store = SecretStore(data_dir)
        store.set("torbox", "key123")
        assert store.load() == {"torbox": "key123"}

    def test_set_empty_value_clears_it(self, data_dir):
        store = SecretStore(data_dir)
        store.set("torbox", "key123")
        store.set("torbox", "")
        assert store.load() == {}

    def test_set_unknown_provider_raises(self, data_dir):
        store = SecretStore(data_dir)
        with pytest.raises(KeyError):
            store.set("not-a-real-provider", "x")

    def test_set_many_partial_update(self, data_dir):
        store = SecretStore(data_dir)
        store.set_many({"torbox": "a", "alldebrid": "b"})
        store.set_many({"torbox": "a2"})  # alldebrid untouched
        assert store.load() == {"torbox": "a2", "alldebrid": "b"}

    def test_delete(self, data_dir):
        store = SecretStore(data_dir)
        store.set("torbox", "key123")
        store.delete("torbox")
        assert store.load() == {}

    def test_encrypted_at_rest_file_does_not_contain_plaintext_key(self, data_dir):
        store = SecretStore(data_dir)
        store.set("torbox", "super-secret-value-xyz")
        raw = (open(f"{data_dir}/secrets.enc", "rb")).read()
        assert b"super-secret-value-xyz" not in raw

    def test_key_file_has_owner_only_permissions(self, data_dir):
        store = SecretStore(data_dir)
        store.set("torbox", "x")
        mode = os.stat(f"{data_dir}/secret.key").st_mode & 0o777
        assert mode == 0o600

    def test_wrong_master_key_raises_clear_error(self, data_dir):
        SecretStore(data_dir, master_key="correct-passphrase").set("torbox", "x")
        wrong = SecretStore(data_dir, master_key="wrong-passphrase")
        with pytest.raises(RuntimeError, match="Cannot decrypt"):
            wrong.load()

    def test_explicit_master_key_survives_store_recreation(self, data_dir):
        SecretStore(data_dir, master_key="my-passphrase").set("torbox", "abc")
        reloaded = SecretStore(data_dir, master_key="my-passphrase")
        assert reloaded.load() == {"torbox": "abc"}


class TestAddonStore:
    def test_upsert_and_load(self, data_dir):
        store = AddonStore(data_dir)
        aid = store.upsert("https://example.com/manifest.json", {"name": "Test"})
        assert store.load()[aid]["url"] == "https://example.com/manifest.json"
        assert store.load()[aid]["name"] == "Test"

    def test_id_is_stable_hash_of_url(self, data_dir):
        store = AddonStore(data_dir)
        url = "https://example.com/manifest.json"
        assert AddonStore.make_id(url) == AddonStore.make_id(url)
        aid = store.upsert(url, {"name": "Test"})
        assert aid == AddonStore.make_id(url)

    def test_reupserting_same_url_updates_not_duplicates(self, data_dir):
        store = AddonStore(data_dir)
        url = "https://example.com/manifest.json"
        id1 = store.upsert(url, {"name": "V1"})
        id2 = store.upsert(url, {"name": "V2"})
        assert id1 == id2
        assert len(store.load()) == 1
        assert store.load()[id1]["name"] == "V2"

    def test_different_urls_get_different_ids(self, data_dir):
        store = AddonStore(data_dir)
        id1 = store.upsert("https://a.example/manifest.json", {"name": "A"})
        id2 = store.upsert("https://b.example/manifest.json", {"name": "B"})
        assert id1 != id2
        assert len(store.load()) == 2

    def test_get_url_returns_none_for_unknown_id(self, data_dir):
        store = AddonStore(data_dir)
        assert store.get_url("nonexistent") is None

    def test_delete_removes_entry(self, data_dir):
        store = AddonStore(data_dir)
        aid = store.upsert("https://example.com/manifest.json", {"name": "Test"})
        store.delete(aid)
        assert store.load() == {}

    def test_encrypted_at_rest_file_does_not_contain_plaintext_url(self, data_dir):
        store = AddonStore(data_dir)
        store.upsert("https://mylumio.tv/SUPERSECRETTOKEN/manifest.json", {"name": "Lumio"})
        raw = open(f"{data_dir}/addons.enc", "rb").read()
        assert b"SUPERSECRETTOKEN" not in raw
        assert b"mylumio" not in raw

    def test_shares_master_key_with_secret_store(self, data_dir):
        """One DEBRID_HUB_SECRET_KEY covers both secrets.enc and addons.enc --
        this is the whole point of factoring key-loading out of SecretStore."""
        SecretStore(data_dir, master_key="shared-key").set("torbox", "provider-key")
        addons = AddonStore(data_dir, master_key="shared-key")
        addons.upsert("https://example.com/manifest.json", {"name": "Test"})
        # both files exist, both decryptable with the same key, only one secret.key
        import os
        assert os.path.exists(f"{data_dir}/secrets.enc")
        assert os.path.exists(f"{data_dir}/addons.enc")
        assert SecretStore(data_dir, master_key="shared-key").load() == {"torbox": "provider-key"}
        assert len(AddonStore(data_dir, master_key="shared-key").load()) == 1


class TestFavoritesStore:
    def test_add_and_list(self, data_dir):
        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "Test Movie", "poster": "https://x/1.jpg", "year": "2020"})
        favs = store.list()
        assert len(favs) == 1
        assert favs[0]["type"] == "movie" and favs[0]["id"] == "tt1"
        assert favs[0]["name"] == "Test Movie"
        assert "added_at" in favs[0]

    def test_same_type_and_id_is_a_stable_key(self, data_dir):
        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "First"})
        store.add("movie", "tt1", {"name": "Updated"})
        favs = store.list()
        assert len(favs) == 1
        assert favs[0]["name"] == "Updated"

    def test_same_id_different_type_is_a_distinct_entry(self, data_dir):
        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "Movie version"})
        store.add("series", "tt1", {"name": "Series version"})
        assert len(store.list()) == 2

    def test_remove(self, data_dir):
        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "Test"})
        store.remove("movie", "tt1")
        assert store.list() == []

    def test_remove_unknown_is_not_an_error(self, data_dir):
        FavoritesStore(data_dir).remove("movie", "does-not-exist")

    def test_list_is_newest_first(self, data_dir):
        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "First"})
        store.add("movie", "tt2", {"name": "Second"})
        favs = store.list()
        assert [f["id"] for f in favs] == ["tt2", "tt1"]

    def test_persists_unencrypted_as_plain_json(self, data_dir):
        import json
        import os

        store = FavoritesStore(data_dir)
        store.add("movie", "tt1", {"name": "Test Movie"})
        path = os.path.join(data_dir, "favorites.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert "Test Movie" in json.dumps(data)

    def test_missing_file_returns_empty_list(self, data_dir):
        assert FavoritesStore(data_dir).list() == []


class TestCredentialStatus:
    def test_reports_none_when_unconfigured(self, data_dir):
        rows = credential_status(Settings(data_dir=data_dir))
        assert all(r["source"] == "none" and not r["configured"] for r in rows)

    def test_reports_env_source(self, data_dir):
        settings = Settings(data_dir=data_dir, torbox_apikey="from-env")
        rows = {r["provider"]: r for r in credential_status(settings)}
        assert rows["torbox"]["source"] == "env"
        assert rows["torbox"]["configured"] is True

    def test_stored_key_takes_priority_over_env_in_status(self, data_dir):
        SecretStore(data_dir).set("torbox", "from-store")
        settings = Settings(data_dir=data_dir, torbox_apikey="from-env")
        rows = {r["provider"]: r for r in credential_status(settings)}
        assert rows["torbox"]["source"] == "stored"

    def test_never_leaks_the_actual_key_value(self, data_dir):
        SecretStore(data_dir).set("torbox", "super-secret-value")
        rows = credential_status(Settings(data_dir=data_dir))
        assert "super-secret-value" not in str(rows)
