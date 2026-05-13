"""Agent self-tunes its own soft preferences in ``config/soul.yaml``.

Hard-locked areas the agent MAY NOT touch here (owner edits the file):
  * ``name``, ``role``, ``tone``
  * ``principles``
  * ``guardrails``

Only specific keys under ``preferences`` are mutable, and each one has a
declared validator. Everything else is rejected. This is the main reason
we have a skill at all rather than "let the LLM rewrite the file".
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from ...config import get_settings, load_soul, load_yaml, save_yaml
from ..base import Skill, SkillContext, SkillError


# Allowlist: key -> (description, validator_fn). Validator returns coerced
# value or raises ValueError.
def _chain_slug(val: Any) -> str:
    # Lazy import so tests don't need chains.yaml present at import time.
    from ...config import load_chains
    chains = load_chains().chains
    if val not in chains:
        raise ValueError(f"unknown chain slug: {val!r}; known: {list(chains)}")
    return str(val)


def _wallet_label(val: Any) -> str:
    from ...wallets import WalletStore
    labels = {w.label for w in WalletStore().list_public()}
    if val not in labels:
        raise ValueError(f"unknown wallet label: {val!r}; known: {sorted(labels)}")
    return str(val)


def _enum(choices: set[str]) -> Callable[[Any], str]:
    def _v(val: Any) -> str:
        s = str(val)
        if s not in choices:
            raise ValueError(f"must be one of {sorted(choices)}, got {val!r}")
        return s
    return _v


ALLOWED: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "default_chain": (
        "Chain slug used when the agent has to pick one.",
        _chain_slug,
    ),
    "default_wallet_label": (
        "Burner wallet label used when the agent has to pick one.",
        _wallet_label,
    ),
    "verbosity": (
        "How chatty responses are. One of: terse, normal, verbose.",
        _enum({"terse", "normal", "verbose"}),
    ),
    "preferred_gas_strategy": (
        "Gas strategy hint. One of: slow, standard, fast.",
        _enum({"slow", "standard", "fast"}),
    ),
}


class UpdatePreferencesInput(BaseModel):
    updates: dict[str, Any] = Field(
        ...,
        description=(
            "Map of preference key -> new value. Only keys in the allowlist "
            "are accepted. Unknown or forbidden keys cause the whole update "
            "to be rejected (all-or-nothing)."
        ),
    )


class UpdatePreferencesOutput(BaseModel):
    changed: dict[str, Any]
    before: dict[str, Any]
    allowlist: list[str]


class UpdatePreferencesSkill(Skill):
    name = "system_update_preferences"
    family = "system"
    description = (
        "Update soft preferences in soul.yaml (e.g. default_chain, verbosity). "
        "Only an explicit allowlist of keys is mutable. Principles and "
        "guardrails are NOT editable via this skill."
    )
    Input = UpdatePreferencesInput
    Output = UpdatePreferencesOutput
    touches_filesystem = True

    async def run(
        self, inputs: UpdatePreferencesInput, ctx: SkillContext
    ) -> UpdatePreferencesOutput:
        if not inputs.updates:
            raise SkillError("no updates provided")

        # All-or-nothing validation first.
        coerced: dict[str, Any] = {}
        for key, raw_val in inputs.updates.items():
            if key not in ALLOWED:
                raise SkillError(
                    f"preference {key!r} is not editable by the agent; "
                    f"allowed keys: {sorted(ALLOWED)}"
                )
            _, validator = ALLOWED[key]
            try:
                coerced[key] = validator(raw_val)
            except ValueError as e:
                raise SkillError(f"validation failed for {key!r}: {e}") from e

        soul_path = get_settings().config_dir / "soul.yaml"
        raw = load_yaml(soul_path)
        current_prefs = dict(raw.get("preferences") or {})
        before = {k: current_prefs.get(k) for k in coerced}
        current_prefs.update(coerced)
        raw["preferences"] = current_prefs
        save_yaml(soul_path, raw)

        # Sanity check: reload via Pydantic to catch YAML corruption.
        try:
            load_soul()
        except Exception as e:  # noqa: BLE001
            raise SkillError(f"soul.yaml reload failed after write: {e}") from e

        return UpdatePreferencesOutput(
            changed=coerced,
            before=before,
            allowlist=sorted(ALLOWED),
        )

    def summary(self, output: UpdatePreferencesOutput) -> str:
        parts = [
            f"{k}: {output.before.get(k)!r} -> {output.changed[k]!r}"
            for k in output.changed
        ]
        return "preferences updated: " + ", ".join(parts)
