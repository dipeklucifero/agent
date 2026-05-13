"""Shared pytest fixtures.

Redirects ``CONFIG_DIR`` / ``DATA_DIR`` / ``KEYSTORE_PASSWORD`` into a
tmp_path per test so every test gets a clean filesystem and doesn't clobber
the dev workspace's ``config/`` or ``data/``.

Clears the ``get_settings`` lru_cache between tests because the Settings
object snapshots env vars at construction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch) -> Path:
    """Set env so the agent reads/writes only inside ``tmp_path``."""
    cfg_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cfg_dir.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("KEYSTORE_PASSWORD", "unit-test-password-long-enough")
    # Required-but-unused-in-tests; just silence preflight.
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "1")

    from agent import config as cfg_mod
    cfg_mod.get_settings.cache_clear()

    return tmp_path


@pytest.fixture
def chains_yaml(isolated_env: Path) -> Path:
    """Write a minimal chains.yaml covering one mainnet + one testnet."""
    cfg_dir = isolated_env / "config"
    chains = {
        "chains": {
            "sepolia": {
                "kind": "evm",
                "chain_id": 11155111,
                "name": "Sepolia",
                "is_testnet": True,
                "rpc_urls": ["https://example.test"],
                "native_symbol": "ETH",
            },
            "ethereum": {
                "kind": "evm",
                "chain_id": 1,
                "name": "Ethereum",
                "is_testnet": False,
                "rpc_urls": ["https://example.test"],
                "native_symbol": "ETH",
            },
        }
    }
    (cfg_dir / "chains.yaml").write_text(yaml.safe_dump(chains))
    (cfg_dir / "policies.yaml").write_text(
        yaml.safe_dump({
            "tx_limits": {"max_tx_usd": 50, "hard_max_tx_usd": 500,
                          "require_mainnet_confirm_string": "CONFIRM MAINNET"},
            "simulate_by_default": True,
            "disabled_skill_families": [],
        })
    )
    return isolated_env
