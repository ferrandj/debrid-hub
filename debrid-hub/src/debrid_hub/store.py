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
_KEY_FILE = "secret.key"


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
        self._key_path = self.dir / _KEY_FILE
        self._master_key = (master_key or "").strip()
        self._fernet: Fernet | None = None

    # -- encryption key ----------------------------------------------------
    def _fernet_obj(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(self._load_or_create_key())
        return self._fernet

    def _load_or_create_key(self) -> bytes:
        if self._master_key:
            return self._normalize_key(self._master_key)
        self.dir.mkdir(parents=True, exist_ok=True)
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        _chmod_600(self._key_path)
        return key

    @staticmethod
    def _normalize_key(raw: str) -> bytes:
        """Accept a real Fernet key verbatim, else derive one from a passphrase."""
        raw_b = raw.encode()
        try:
            Fernet(raw_b)  # validates format + length
            return raw_b
        except (ValueError, TypeError):
            digest = hashlib.sha256(raw_b).digest()
            return base64.urlsafe_b64encode(digest)

    # -- read / write ------------------------------------------------------
    def load(self) -> dict[str, str]:
        """Return the decrypted, non-empty managed credentials (may be empty)."""
        if not self._secrets_path.exists():
            return {}
        try:
            raw = self._fernet_obj().decrypt(self._secrets_path.read_bytes())
        except InvalidToken as exc:
            raise RuntimeError(
                "Cannot decrypt the credential store — the master key changed or "
                "the store is corrupt. Fix DEBRID_HUB_SECRET_KEY or delete "
                f"{self._secrets_path} to start over."
            ) from exc
        data = json.loads(raw)
        return {k: v for k, v in data.items() if k in MANAGED and v}

    def _save(self, data: dict[str, str]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {k: v for k, v in data.items() if k in MANAGED and v},
            separators=(",", ":"),
        ).encode()
        token = self._fernet_obj().encrypt(payload)
        tmp = self._secrets_path.with_suffix(".tmp")
        tmp.write_bytes(token)
        _chmod_600(tmp)
        os.replace(tmp, self._secrets_path)  # atomic on the same filesystem

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


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # e.g. Windows / exotic filesystems — best effort


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
