"""Pre-tool-call guardrails.

Runs BEFORE the skill executes. Three responsibilities:

1. Enforce kill switches (``disabled_skill_families``).
2. Enforce mainnet-confirm string for mainnet-touching skills.
3. Inject ``simulate=True`` when the policy demands simulate-first and
   the LLM forgot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import load_chains, load_policies
from .skills import Skill, SkillDenied


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    # Mutated args to pass to the skill (e.g., with simulate=True forced).
    args: dict[str, Any] | None = None


class PolicyEngine:
    def check(
        self,
        *,
        skill: Skill,
        args: dict[str, Any],
        user_turn_text: str,
    ) -> PolicyDecision:
        pol = load_policies()

        if skill.family in pol.disabled_skill_families:
            return PolicyDecision(False, f"family '{skill.family}' disabled by /disable")

        new_args = dict(args)

        # --- Simulate-first on chain-mutating skills ------------------
        if skill.mutates_chain and pol.simulate_by_default:
            if new_args.get("simulate") is None:
                new_args["simulate"] = True

        # --- Mainnet confirm ------------------------------------------
        chain_slug = new_args.get("chain") or new_args.get("chain_slug")
        if chain_slug:
            chain = load_chains().chains.get(chain_slug)
            if chain is not None and not chain.is_testnet and skill.mutates_chain:
                # Only enforce if the tx would actually broadcast (not simulate).
                if not new_args.get("simulate", False):
                    need = pol.tx_limits.require_mainnet_confirm_string
                    if need not in (user_turn_text or ""):
                        return PolicyDecision(
                            False,
                            f"mainnet tx requires '{need}' in the same turn",
                        )

        return PolicyDecision(True, args=new_args)


class PolicyViolation(SkillDenied):
    """Raised by the agent loop when policy rejects a call."""
