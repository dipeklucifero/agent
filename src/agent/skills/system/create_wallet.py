"""Generate a fresh burner wallet (EVM or Solana) and persist encrypted.

Returns the PUBLIC address only. Private key never leaves the keystore.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...config import load_policies
from ...memory import EpisodicMemory
from ...wallets import WalletStore
from ...wallets.evm import create_evm_wallet
from ...wallets.solana import create_solana_wallet
from ..base import Skill, SkillContext, SkillDenied


class CreateWalletInput(BaseModel):
    kind: Literal["evm", "solana"] = "evm"
    label: str | None = Field(
        default=None,
        description=(
            "Optional label, e.g. 'burner-monad'. If omitted, auto-generates "
            "'burner-<kind>-<n>' picking the next free integer."
        ),
    )


class CreateWalletOutput(BaseModel):
    label: str
    kind: str
    address: str


class CreateWalletSkill(Skill):
    name = "system.create_wallet"
    family = "system"
    description = (
        "Generate a new burner wallet for EVM or Solana and store the private "
        "key encrypted (AES-256-GCM). Returns only the public address. "
        "Private keys NEVER leave the agent process."
    )
    Input = CreateWalletInput
    Output = CreateWalletOutput
    touches_filesystem = True

    async def run(self, inputs: CreateWalletInput, ctx: SkillContext) -> CreateWalletOutput:
        policy = load_policies().self_dev
        if not policy.allow_create_wallet:
            raise SkillDenied("create_wallet disabled by policy")

        episodic = EpisodicMemory()
        count_today = episodic.counter("wallets_created")
        if count_today >= policy.max_new_wallets_per_day:
            raise SkillDenied(
                f"daily wallet creation cap reached "
                f"({count_today}/{policy.max_new_wallets_per_day}); "
                f"owner must raise self_dev.max_new_wallets_per_day"
            )

        store = WalletStore()
        label = inputs.label or _next_label(store, inputs.kind)

        if inputs.kind == "evm":
            w = create_evm_wallet()
            rec = store.save(label=label, kind="evm", address=w.address, private_key=w.private_key)
        else:
            sw = create_solana_wallet()
            rec = store.save(label=label, kind="solana", address=sw.address, private_key=sw.private_key)

        episodic.bump_counter("wallets_created")
        return CreateWalletOutput(label=rec.label, kind=rec.kind, address=rec.address)

    def summary(self, output: CreateWalletOutput) -> str:
        return f"created {output.kind} wallet '{output.label}' -> {output.address}"


def _next_label(store: WalletStore, kind: str) -> str:
    existing = {w.label for w in store.list_public()}
    i = 1
    while True:
        candidate = f"burner-{kind}-{i}"
        if candidate not in existing:
            return candidate
        i += 1
