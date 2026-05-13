"""Tests for the encrypted wallet keystore.

Covers:
  * roundtrip: save() -> list_public() -> unlock() returns original bytes
  * wrong password: KEYSTORE_PASSWORD mid-test change -> KeystoreError
  * AEAD tamper detection: flipping a byte of ciphertext -> KeystoreError
  * AAD tamper detection: renaming the file so label != associated_data
    -> KeystoreError
  * duplicate label: save() raises
  * invalid label characters: sanitised path, empty sanitised label raises
"""

from __future__ import annotations

import base64
import json
import os

import pytest

from agent.wallets.store import KeystoreError, WalletStore


def test_save_and_unlock_roundtrip(isolated_env):
    store = WalletStore()
    pk = b"\x01" * 32
    rec = store.save(label="burner-evm-1", kind="evm",
                     address="0xabc0000000000000000000000000000000000001",
                     private_key=pk)

    assert rec.label == "burner-evm-1"
    assert rec.kind == "evm"

    listed = store.list_public()
    assert [w.label for w in listed] == ["burner-evm-1"]
    # Public listing must never leak the key material.
    assert not any("ciphertext" in w.__dict__ for w in listed)

    with store.unlock("burner-evm-1") as got:
        assert bytes(got) == pk


def test_wrong_password_fails_decrypt(isolated_env, monkeypatch):
    store = WalletStore()
    store.save(label="w1", kind="evm", address="0x" + "1" * 40,
               private_key=b"\x02" * 32)

    # Rotate the password. Cache must be cleared so new password is picked up.
    monkeypatch.setenv("KEYSTORE_PASSWORD", "a-different-password")
    from agent import config as cfg_mod
    cfg_mod.get_settings.cache_clear()

    with pytest.raises(KeystoreError):
        with store.unlock("w1"):
            pass


def test_tampered_ciphertext_fails(isolated_env):
    store = WalletStore()
    store.save(label="t1", kind="evm", address="0x" + "2" * 40,
               private_key=b"\x03" * 32)

    path = isolated_env / "data" / "keystore" / "t1.json"
    doc = json.loads(path.read_text())
    ct = bytearray(base64.b64decode(doc["ciphertext"]))
    ct[0] ^= 0xFF  # flip one byte
    doc["ciphertext"] = base64.b64encode(bytes(ct)).decode()
    path.write_text(json.dumps(doc))

    with pytest.raises(KeystoreError):
        with store.unlock("t1"):
            pass


def test_label_is_aad_so_renaming_file_breaks_decryption(isolated_env):
    """The label is bound into AESGCM's associated_data. Copying the file
    to another label must fail auth, even though the ciphertext is valid."""
    store = WalletStore()
    store.save(label="src", kind="evm", address="0x" + "3" * 40,
               private_key=b"\x04" * 32)

    keystore = isolated_env / "data" / "keystore"
    src = keystore / "src.json"
    dst = keystore / "copied.json"
    doc = json.loads(src.read_text())
    # Simulate: attacker renames the file but leaves the inner 'label' and
    # AAD intact. Store._read uses the filename stem as the lookup key, so
    # to actually be attacked we'd also need to edit 'label' inside.
    doc["label"] = "copied"
    dst.write_text(json.dumps(doc))

    with pytest.raises(KeystoreError):
        with store.unlock("copied"):
            pass


def test_duplicate_label_raises(isolated_env):
    store = WalletStore()
    store.save(label="dup", kind="evm", address="0x" + "5" * 40,
               private_key=b"\x06" * 32)
    with pytest.raises(KeystoreError):
        store.save(label="dup", kind="evm", address="0x" + "6" * 40,
                   private_key=b"\x07" * 32)


def test_invalid_label_rejected(isolated_env):
    store = WalletStore()
    with pytest.raises(KeystoreError):
        store.save(label="///", kind="evm", address="0x" + "7" * 40,
                   private_key=b"\x08" * 32)


def test_keystore_file_is_mode_0600(isolated_env):
    store = WalletStore()
    store.save(label="perm", kind="evm", address="0x" + "9" * 40,
               private_key=b"\x0a" * 32)
    p = isolated_env / "data" / "keystore" / "perm.json"
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
