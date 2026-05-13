"""Tests for PolicyEngine.

Covers every branch in ``policy.PolicyEngine.check``:

  1. family in disabled_skill_families -> allowed=False
  2. mutates_chain + simulate_by_default + no simulate -> simulate injected
  3. mutates_chain + simulate=False explicit + mainnet + no CONFIRM -> denied
  4. mutates_chain + simulate=False + mainnet + CONFIRM present -> allowed
  5. mutates_chain + mainnet + simulate=True -> allowed (not enforced)
  6. mutates_chain + testnet (no confirm) -> allowed
  7. non-mutating skill on mainnet without confirm -> allowed (read-only)
"""

from __future__ import annotations

from pydantic import BaseModel

from agent.policy import PolicyEngine
from agent.skills.base import Skill, SkillContext


class _In(BaseModel):
    chain_slug: str | None = None
    simulate: bool | None = None


class _Out(BaseModel):
    ok: bool = True


class _Mutator(Skill):
    name = "test_mutator"
    family = "wallet"
    description = "test"
    Input = _In
    Output = _Out
    mutates_chain = True

    async def run(self, inputs, ctx):  # pragma: no cover
        return _Out()


class _Reader(Skill):
    name = "test_reader"
    family = "research"
    description = "test"
    Input = _In
    Output = _Out
    mutates_chain = False

    async def run(self, inputs, ctx):  # pragma: no cover
        return _Out()


def _kill_switch_policy(tmp_path, disabled: list[str]):
    """Write a policies.yaml with a specific disabled list."""
    import yaml
    (tmp_path / "config" / "policies.yaml").write_text(
        yaml.safe_dump({
            "tx_limits": {"max_tx_usd": 50, "hard_max_tx_usd": 500,
                          "require_mainnet_confirm_string": "CONFIRM MAINNET"},
            "simulate_by_default": True,
            "disabled_skill_families": disabled,
        })
    )


def test_disabled_family_is_denied(chains_yaml):
    _kill_switch_policy(chains_yaml, ["wallet"])
    decision = PolicyEngine().check(
        skill=_Mutator(), args={}, user_turn_text="anything",
    )
    assert not decision.allowed
    assert "disabled" in decision.reason


def test_simulate_is_injected_when_missing(chains_yaml):
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "sepolia"},
        user_turn_text="do a tx",
    )
    assert decision.allowed
    assert decision.args is not None
    assert decision.args["simulate"] is True


def test_existing_simulate_is_preserved(chains_yaml):
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "sepolia", "simulate": False},
        user_turn_text="CONFIRM MAINNET", # irrelevant on testnet
    )
    assert decision.allowed
    assert decision.args["simulate"] is False


def test_mainnet_without_confirm_is_denied(chains_yaml):
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "ethereum", "simulate": False},
        user_turn_text="send 1 eth",
    )
    assert not decision.allowed
    assert "mainnet" in decision.reason.lower()


def test_mainnet_with_confirm_is_allowed(chains_yaml):
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "ethereum", "simulate": False},
        user_turn_text="send 0.001 eth CONFIRM MAINNET",
    )
    assert decision.allowed


def test_mainnet_with_simulate_true_bypasses_confirm(chains_yaml):
    """Simulating a mainnet tx is harmless; don't require CONFIRM MAINNET."""
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "ethereum", "simulate": True},
        user_turn_text="dry run please",
    )
    assert decision.allowed


def test_testnet_never_requires_confirm(chains_yaml):
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain_slug": "sepolia", "simulate": False},
        user_turn_text="go",
    )
    assert decision.allowed


def test_reader_on_mainnet_is_fine(chains_yaml):
    """Read-only skills never trip the confirm check."""
    decision = PolicyEngine().check(
        skill=_Reader(),
        args={"chain_slug": "ethereum"},
        user_turn_text="what's the balance",
    )
    assert decision.allowed


def test_chain_key_can_also_be_named_chain(chains_yaml):
    """Policy should accept both 'chain' and 'chain_slug' arg names."""
    decision = PolicyEngine().check(
        skill=_Mutator(),
        args={"chain": "ethereum", "simulate": False},
        user_turn_text="send it",
    )
    assert not decision.allowed  # mainnet without CONFIRM
