"""Enumerate burner wallets (public info only)."""

from __future__ import annotations

from pydantic import BaseModel

from ...wallets import WalletStore
from ..base import Skill, SkillContext


class ListWalletsInput(BaseModel):
    pass


class WalletInfo(BaseModel):
    label: str
    kind: str
    address: str
    created_ts: str


class ListWalletsOutput(BaseModel):
    wallets: list[WalletInfo]


class ListWalletsSkill(Skill):
    name = "system_list_wallets"
    family = "system"
    description = "List all burner wallets (public addresses only)."
    Input = ListWalletsInput
    Output = ListWalletsOutput

    async def run(self, inputs: ListWalletsInput, ctx: SkillContext) -> ListWalletsOutput:
        records = WalletStore().list_public()
        return ListWalletsOutput(
            wallets=[
                WalletInfo(
                    label=r.label, kind=r.kind, address=r.address,
                    created_ts=r.created_ts,
                )
                for r in records
            ]
        )

    def summary(self, output: ListWalletsOutput) -> str:
        if not output.wallets:
            return "no wallets"
        return ", ".join(f"{w.label}({w.kind})" for w in output.wallets)
