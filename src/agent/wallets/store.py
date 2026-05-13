"""Encrypted keystore.

Design
------
* One JSON file per wallet: ``data/keystore/<label>.json``.
* Private key is AES-256-GCM encrypted.
* Key is derived from ``KEYSTORE_PASSWORD`` via scrypt with per-wallet salt.
* Only the ``unlock()`` context manager exposes the raw key, and only
  to code running in-process. The LLM never sees the key.
* ``list_public()`` returns addresses only, safe to log and send to the LLM.

File format (JSON)::

    {
        "label": "burner-1",
        "kind": "evm",          # or "solana"
        "address": "0x...",     # EVM: checksum; Solana: base58
        "created_ts": "2025-...",
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "kdf_params": {"n": 2**15, "r": 8, "p": 1, "salt": "<b64>"},
        "nonce": "<b64>",
        "ciphertext": "<b64>"
    }
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..config import get_settings

_SCRYPT_N = 2**15       # ~32MB memory, ~0.1s on a typical CPU
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32           # AES-256


class KeystoreError(Exception):
    pass


Kind = Literal["evm", "solana"]


@dataclass
class WalletRecord:
    label: str
    kind: Kind
    address: str
    created_ts: str


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(password.encode("utf-8"))


class WalletStore:
    """Filesystem-backed encrypted keystore."""

    def __init__(self, dir_path: Path | None = None) -> None:
        self._dir = dir_path or (get_settings().data_dir / "keystore")
        self._dir.mkdir(parents=True, exist_ok=True)

    # ----- internal IO ---------------------------------------------------
    def _path(self, label: str) -> Path:
        safe = "".join(c for c in label if c.isalnum() or c in "-_")
        if not safe:
            raise KeystoreError(f"invalid label: {label!r}")
        return self._dir / f"{safe}.json"

    def _read(self, label: str) -> dict:
        path = self._path(label)
        if not path.exists():
            raise KeystoreError(f"wallet not found: {label}")
        return json.loads(path.read_text())

    def _write(self, label: str, payload: dict) -> None:
        path = self._path(label)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ----- public API ----------------------------------------------------
    def exists(self, label: str) -> bool:
        return self._path(label).exists()

    def list_public(self) -> list[WalletRecord]:
        out: list[WalletRecord] = []
        for p in sorted(self._dir.glob("*.json")):
            d = json.loads(p.read_text())
            out.append(
                WalletRecord(
                    label=d["label"],
                    kind=d["kind"],
                    address=d["address"],
                    created_ts=d.get("created_ts", ""),
                )
            )
        return out

    def save(self, *, label: str, kind: Kind, address: str, private_key: bytes) -> WalletRecord:
        """Encrypt + persist a private key. Raises if label already exists."""
        if self.exists(label):
            raise KeystoreError(f"wallet already exists: {label}")
        password = get_settings().keystore_password
        if not password:
            raise KeystoreError("KEYSTORE_PASSWORD is not set")

        salt = os.urandom(16)
        key = _derive_key(password, salt)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, private_key, associated_data=label.encode())

        record = {
            "label": label,
            "kind": kind,
            "address": address,
            "created_ts": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "cipher": "AES-256-GCM",
            "kdf": "scrypt",
            "kdf_params": {
                "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
                "salt": _b64e(salt),
            },
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(ct),
        }
        self._write(label, record)
        return WalletRecord(label=label, kind=kind, address=address,
                            created_ts=record["created_ts"])

    @contextmanager
    def unlock(self, label: str) -> Iterator[bytes]:
        """Yield the decrypted private key bytes. Caller must not persist."""
        d = self._read(label)
        password = get_settings().keystore_password
        if not password:
            raise KeystoreError("KEYSTORE_PASSWORD is not set")
        salt = _b64d(d["kdf_params"]["salt"])
        # Re-derive with the stored params (future-proof against param bumps).
        kdf = Scrypt(
            salt=salt,
            length=_KEY_LEN,
            n=d["kdf_params"]["n"],
            r=d["kdf_params"]["r"],
            p=d["kdf_params"]["p"],
        )
        key = kdf.derive(password.encode())
        try:
            pk = AESGCM(key).decrypt(
                _b64d(d["nonce"]),
                _b64d(d["ciphertext"]),
                associated_data=d["label"].encode(),
            )
        except Exception as e:
            raise KeystoreError("failed to decrypt (wrong password?)") from e
        try:
            yield pk
        finally:
            # Best-effort wipe. Python makes this imperfect but we try.
            try:
                mv = memoryview(bytearray(pk))
                for i in range(len(mv)):
                    mv[i] = 0
            except Exception:
                pass
