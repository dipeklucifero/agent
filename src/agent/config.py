"""Central configuration loader.

Merges three sources:
  1. Environment variables (.env) - secrets and runtime knobs.
  2. YAML files in config/ - soul, chains, contacts, policies.
  3. Defaults baked into the Pydantic models below.

YAML files are considered *mutable state*: some agent skills write back to
them (e.g. ``add_rpc``). All YAML writes go through :func:`save_yaml` which
serialises atomically via a tempfile + rename.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-relative default. Overridden by env var if set.
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

load_dotenv()


class Settings(BaseSettings):
    """Environment-backed secrets & runtime knobs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    hermes_model: str = Field(
        default="nousresearch/hermes-4-70b", alias="HERMES_MODEL"
    )
    hermes_fallback_model: str = Field(
        default="nousresearch/hermes-3-llama-3.1-8b",
        alias="HERMES_FALLBACK_MODEL",
    )

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_id: int = Field(default=0, alias="TELEGRAM_OWNER_ID")
    telegram_audit_chat_id: str = Field(default="", alias="TELEGRAM_AUDIT_CHAT_ID")

    # Telethon (userbot)
    telegram_api_id: str = Field(default="", alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(default="", alias="TELEGRAM_API_HASH")
    telethon_session: str = Field(
        default="/app/data/userbot.session", alias="TELETHON_SESSION"
    )

    # Keystore
    keystore_password: str = Field(default="", alias="KEYSTORE_PASSWORD")

    # X
    x_username: str = Field(default="", alias="X_USERNAME")
    x_email: str = Field(default="", alias="X_EMAIL")
    x_password: str = Field(default="", alias="X_PASSWORD")
    x_cookies_path: str = Field(
        default="/app/data/x_cookies.json", alias="X_COOKIES_PATH"
    )

    # Discord
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")

    # Paths (allow override for tests)
    config_dir: Path = Field(default=_DEFAULT_CONFIG_DIR, alias="CONFIG_DIR")
    data_dir: Path = Field(default=_DEFAULT_DATA_DIR, alias="DATA_DIR")


# ---------------------------------------------------------------------------
# YAML-backed config models
# ---------------------------------------------------------------------------


class Chain(BaseModel):
    kind: Literal["evm", "solana"]
    name: str
    is_testnet: bool
    rpc_urls: list[str]
    explorer: str = ""
    native_symbol: str = ""
    chain_id: int | None = None  # required for EVM


class ChainsConfig(BaseModel):
    chains: dict[str, Chain] = Field(default_factory=dict)


class Contact(BaseModel):
    label: str
    address: str
    chain_kind: Literal["evm", "solana"]
    notes: str = ""


class ContactsConfig(BaseModel):
    contacts: list[Contact] = Field(default_factory=list)


class TxLimits(BaseModel):
    max_tx_usd: float = 50
    hard_max_tx_usd: float = 500
    require_mainnet_confirm_string: str = "CONFIRM MAINNET"


class SocialPacing(BaseModel):
    min: int
    max: int


class SelfDevLimits(BaseModel):
    allow_add_rpc: bool = True
    allow_create_wallet: bool = True
    allow_add_contact: bool = True
    allow_propose_skill: bool = True
    max_new_wallets_per_day: int = 10


class PoliciesConfig(BaseModel):
    tx_limits: TxLimits = Field(default_factory=TxLimits)
    simulate_by_default: bool = True
    allow_eip1559: bool = True
    disabled_skill_families: list[str] = Field(default_factory=list)
    social_pacing: dict[str, SocialPacing] = Field(default_factory=dict)
    self_dev: SelfDevLimits = Field(default_factory=SelfDevLimits)


class SoulConfig(BaseModel):
    name: str = "Hermes"
    role: str = ""
    tone: str = ""
    principles: list[str] = Field(default_factory=list)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomic YAML write. Agent skills use this when mutating config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _cfg_path(name: str) -> Path:
    return get_settings().config_dir / name


def load_soul() -> SoulConfig:
    return SoulConfig(**load_yaml(_cfg_path("soul.yaml")))


def load_chains() -> ChainsConfig:
    return ChainsConfig(**load_yaml(_cfg_path("chains.yaml")))


def save_chains(cfg: ChainsConfig) -> None:
    save_yaml(_cfg_path("chains.yaml"), cfg.model_dump())


def load_contacts() -> ContactsConfig:
    return ContactsConfig(**load_yaml(_cfg_path("contacts.yaml")))


def save_contacts(cfg: ContactsConfig) -> None:
    save_yaml(_cfg_path("contacts.yaml"), cfg.model_dump())


def load_policies() -> PoliciesConfig:
    return PoliciesConfig(**load_yaml(_cfg_path("policies.yaml")))
