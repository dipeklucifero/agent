"""Build the system prompt from soul.yaml + live state.

The soul is re-read on every turn so owner edits take effect without a
restart. Cost is negligible (one tiny YAML parse).
"""

from __future__ import annotations

from .config import load_chains, load_policies, load_soul
from .wallets import WalletStore


def build_system_prompt() -> str:
    soul = load_soul()
    policies = load_policies()
    chains = load_chains().chains

    # Public wallet list is safe to include; private keys never appear.
    wallets = WalletStore().list_public()
    wallet_lines = (
        "\n".join(f"  - {w.label} ({w.kind}): {w.address}" for w in wallets)
        or "  (none yet - use system.create_wallet)"
    )

    chain_lines = "\n".join(
        f"  - {slug}: {c.name} ({'testnet' if c.is_testnet else 'MAINNET'},"
        f" kind={c.kind}, id={c.chain_id or 'n/a'})"
        for slug, c in chains.items()
    )

    principles = "\n".join(f"  - {p}" for p in soul.principles)
    disabled = ", ".join(policies.disabled_skill_families) or "(none)"

    return f"""You are {soul.name}, {soul.role}.
Tone: {soul.tone}

# Operating principles
{principles}

# Guardrails
- Simulate first on any chain-mutating action.
- Max tx value without explicit confirm: ${policies.tx_limits.max_tx_usd}.
- Mainnet actions require the string "{policies.tx_limits.require_mainnet_confirm_string}" in the same turn.
- Disabled skill families: {disabled}
- Private keys are managed by the keystore. You never see them. Refer to wallets by label.

# Configured chains
{chain_lines}

# Wallets
{wallet_lines}

# Preferences (editable by you via future update_preferences skill)
- default_chain: {soul.preferences.get('default_chain')}
- default_wallet_label: {soul.preferences.get('default_wallet_label')}
- verbosity: {soul.preferences.get('verbosity')}

# Interaction style
Be terse. Prefer bullet points. When you call a tool, explain in one line what
and why, then call it. When a user instruction is ambiguous or risky, ask one
precise clarifying question. Never make up tool results.
"""
