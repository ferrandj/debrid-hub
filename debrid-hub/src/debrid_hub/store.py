from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# Provider credentials we manage in the encrypted store. These map onto the
# matching env-var fields on Settings (see aggregator._build / credential_status).
MANAGED: tuple[str, ...] = ("realdebrid", "alldebrid", "torbox")

_SECRETS_FILE = "secrets.enc"
_ADDONS_FILE = "addons.enc"
_KEY_FILE = "secret.key"


def _normalize_key(raw: str) -> bytes:
    """Accept a real Fernet key verbatim, else derive one from a passphrase."""
    raw_b = raw.encode()
    try:
        Fernet(raw_b)  # validates format + length
        return raw_b
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw_b).digest()
        return base64.urlsafe_b64encode(digest)


def _load_or_create_key(data_dir: Path, master_key: str) -> bytes:
    """One master key for the whole encrypted store directory -- every file in
    it (secrets.enc, addons.enc, ...) is encrypted with the same derived key,
    so a single DEBRID_HUB_SECRET_KEY (or a single generated secret.key)
    covers all of them."""
    if master_key:
        return _normalize_key(master_key)
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / _KEY_FILE
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    _chmod_600(key_path)
    return key


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # e.g. Windows / exotic filesystems — best effort


def _write_encrypted(path: Path, fernet: Fernet, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = fernet.encrypt(payload)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(token)
    _chmod_600(tmp)
    os.replace(tmp, path)  # atomic on the same filesystem


def _read_encrypted(path: Path, fernet: Fernet, what: str) -> bytes | None:
    if not path.exists():
        return None
    try:
        return fernet.decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError(
            f"Cannot decrypt {what} — the master key changed or the store is "
            f"corrupt. Fix DEBRID_HUB_SECRET_KEY or delete {path} to start over."
        ) from exc


class SecretStore:
    """Encrypted-at-rest storage for provider API keys.

    Keys live in `<data_dir>/secrets.enc`, encrypted with Fernet (AES-128-CBC +
    HMAC). The master key comes from `DEBRID_HUB_SECRET_KEY` if set (a Fernet key
    or any passphrase, from which a key is derived); otherwise a random key is
    generated once and kept in `<data_dir>/secret.key` with 0600 perms.

    Losing the master key (or the generated key file) makes the stored secrets
    unrecoverable — that is the point of encrypting them.
    """

    def __init__(self, data_dir: str, master_key: str = "") -> None:
        self.dir = Path(data_dir).expanduser()
        self._secrets_path = self.dir / _SECRETS_FILE
        self._master_key = (master_key or "").strip()
        self._fernet: Fernet | None = None

    def _fernet_obj(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(_load_or_create_key(self.dir, self._master_key))
        return self._fernet

    # -- read / write ------------------------------------------------------
    def load(self) -> dict[str, str]:
        """Return the decrypted, non-empty managed credentials (may be empty)."""
        raw = _read_encrypted(self._secrets_path, self._fernet_obj(), "the credential store")
        if raw is None:
            return {}
        data = json.loads(raw)
        return {k: v for k, v in data.items() if k in MANAGED and v}

    def _save(self, data: dict[str, str]) -> None:
        payload = json.dumps(
            {k: v for k, v in data.items() if k in MANAGED and v},
            separators=(",", ":"),
        ).encode()
        _write_encrypted(self._secrets_path, self._fernet_obj(), payload)

    def set(self, provider: str, value: str) -> None:
        if provider not in MANAGED:
            raise KeyError(f"unknown provider '{provider}'")
        data = self.load()
        value = (value or "").strip()
        if value:
            data[provider] = value
        else:
            data.pop(provider, None)
        self._save(data)

    def set_many(self, updates: dict[str, str]) -> None:
        data = self.load()
        for provider, value in updates.items():
            if provider not in MANAGED:
                continue
            value = (value or "").strip()
            if value:
                data[provider] = value
            else:
                data.pop(provider, None)
        self._save(data)

    def delete(self, provider: str) -> None:
        self.set(provider, "")


class AddonStore:
    """Encrypted-at-rest storage for Stremio-protocol addon manifest URLs.

    A manifest URL commonly embeds a personal config token (debrid keys,
    account id, ...) baked into the path -- handled exactly like a provider
    API key: encrypted in `<data_dir>/addons.enc` (shares the same master key
    as SecretStore, in its own file), never returned in plaintext by any API
    response once stored, never written anywhere outside this store.

    Entries are keyed by a stable id derived from the URL (sha256 prefix), so
    re-adding the same URL updates in place instead of duplicating, and so ids
    are safe to hand to the browser / put in a URL without leaking the addon URL.
    """

    def __init__(self, data_dir: str, master_key: str = "") -> None:
        self.dir = Path(data_dir).expanduser()
        self._path = self.dir / _ADDONS_FILE
        self._master_key = (master_key or "").strip()
        self._fernet: Fernet | None = None

    def _fernet_obj(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(_load_or_create_key(self.dir, self._master_key))
        return self._fernet

    @staticmethod
    def make_id(url: str) -> str:
        return hashlib.sha256(url.strip().encode()).hexdigest()[:12]

    def load(self) -> dict[str, dict]:
        """id -> {url, name, resources, types, catalogs}"""
        raw = _read_encrypted(self._path, self._fernet_obj(), "the addon store")
        if raw is None:
            return {}
        return json.loads(raw)

    def _save(self, data: dict[str, dict]) -> None:
        payload = json.dumps(data, separators=(",", ":")).encode()
        _write_encrypted(self._path, self._fernet_obj(), payload)

    def upsert(self, url: str, meta: dict) -> str:
        """Store (or update) one addon entry. `meta` is whatever non-secret
        summary fields to cache alongside it (name, resources, types, catalogs).
        Returns the entry's id."""
        aid = self.make_id(url)
        data = self.load()
        data[aid] = {"id": aid, "url": url.strip(), **meta}
        self._save(data)
        return aid

    def get_url(self, addon_id: str) -> str | None:
        return self.load().get(addon_id, {}).get("url")

    def delete(self, addon_id: str) -> None:
        data = self.load()
        data.pop(addon_id, None)
        self._save(data)


def credential_status(settings) -> list[dict]:
    """Report, per managed provider, whether a credential is configured and from
    where ("stored" = encrypted store, "env" = env var, "none"). Never leaks the
    key value itself."""
    store = SecretStore(settings.data_dir, settings.secret_key)
    stored = store.load()
    env = {
        "realdebrid": settings.realdebrid_token,
        "alldebrid": settings.alldebrid_apikey,
        "torbox": settings.torbox_apikey,
    }
    rows: list[dict] = []
    for name in MANAGED:
        if stored.get(name):
            source = "stored"
        elif env.get(name):
            source = "env"
        else:
            source = "none"
        rows.append(
            {"provider": name, "configured": source != "none", "source": source}
        )
    return rows
