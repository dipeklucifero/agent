"""Add a labelled address to the shared contacts book (config/contacts.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...config import Contact, load_contacts, load_policies, save_contacts
from ..base import Skill, SkillContext, SkillDenied, SkillError


class AddContactInput(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    address: str
    chain_kind: Literal["evm", "solana"]
    notes: str = ""


class AddContactOutput(BaseModel):
    label: str
    address: str


class AddContactSkill(Skill):
    name = "system_add_contact"
    family = "system"
    description = "Add a labelled address to the contacts book for later reference."
    Input = AddContactInput
    Output = AddContactOutput
    touches_filesystem = True

    async def run(self, inputs: AddContactInput, ctx: SkillContext) -> AddContactOutput:
        if not load_policies().self_dev.allow_add_contact:
            raise SkillDenied("add_contact disabled by policy")

        cfg = load_contacts()
        if any(c.label == inputs.label for c in cfg.contacts):
            raise SkillError(f"contact already exists: {inputs.label}")

        cfg.contacts.append(
            Contact(
                label=inputs.label,
                address=inputs.address,
                chain_kind=inputs.chain_kind,
                notes=inputs.notes,
            )
        )
        save_contacts(cfg)
        return AddContactOutput(label=inputs.label, address=inputs.address)

    def summary(self, output: AddContactOutput) -> str:
        return f"added contact '{output.label}' -> {output.address}"
