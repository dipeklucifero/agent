"""Daily testnet tick.

The boring-but-profitable ritual: each day, send a zero-value self-tx on
each testnet to accumulate an on-chain activity streak. Delegates all the
actual chain work to :mod:`agent.skills.wallet.send`.

Design choices:
  * Default ``to`` = sender (self-tx). Safe, no capital at risk beyond gas.
  * Optional ``jitter_seconds``: sleep a random 0..N before broadcasting so
    scheduled cron runs don't all hit the RPC at the same wall-clock moment.
  * Idempotency: episodic memory tracks the day's last successful tx per
    chain+wallet pair via the ``counters`` table. Re-running the same day
    is explicit-only (``force=True``).
"""

from __future__ import annotations

import asyncio
import random

from pydantic import BaseModel, Field

from ...config import load_chains
from ...memory import EpisodicMemory
from ...wallets import WalletStore
from ..base import Skill, SkillContext, SkillError
from ..wallet.send import SendInput, WalletSendSkill


class DailyTxInput(BaseModel):
    chain_slug: str = Field(..., description="EVM testnet slug (e.g. 'monad_testnet').")
    wallet_label: str = Field(..., description="Sender wallet label.")
    to: str | None = Field(
        default=None,
        description="Recipient. Defaults to the sender (self-tx) if omitted.",
    )
    jitter_seconds: int = Field(
        default=0,
        ge=0, le=3600,
        description="Random sleep 0..N before broadcasting. Use on scheduled runs.",
    )
    simulate: bool | None = Field(
        default=None,
        description="Forward to wallet_send; policy may override to True.",
    )
    force: bool = Field(
        default=False,
        description="Run even if today's daily tx was already logged for this chain/wallet.",
    )


class DailyTxOutput(BaseModel):
    chain: str
    wallet_label: str
    skipped: bool = False
    skip_reason: str | None = None
    tx_hash: str | None = None
    status: str
    explorer_url: str | None = None
    simulated: bool = False


class DailyTxSkill(Skill):
    name = "testnet_daily_tx"
    family = "testnet"
    description = (
        "Send a zero-value self-transaction on a testnet to tick a daily activity "
        "streak. Refuses if mainnet. Idempotent per (chain, wallet, day) unless "
        "force=True. Honours jitter_seconds to de-correlate scheduled runs."
    )
    Input = DailyTxInput
    Output = DailyTxOutput
    mutates_chain = True

    async def run(self, inputs: DailyTxInput, ctx: SkillContext) -> DailyTxOutput:
        chains = load_chains().chains
        chain = chains.get(inputs.chain_slug)
        if chain is None:
            raise SkillError(f"unknown chain: {inputs.chain_slug}")
        if chain.kind != "evm":
            raise SkillError("daily_tx currently supports EVM chains only")
        if not chain.is_testnet:
            raise SkillError(
                f"daily_tx refuses mainnet chain '{inputs.chain_slug}'. "
                "Use wallet_send with CONFIRM MAINNET if that's really what you want."
            )

        # Idempotency check (cheap: one SQLite counter).
        ep = EpisodicMemory()
        counter_key = f"daily_tx:{inputs.chain_slug}:{inputs.wallet_label}"
        already = ep.counter(counter_key)
        if already and not inputs.force:
            return DailyTxOutput(
                chain=inputs.chain_slug,
                wallet_label=inputs.wallet_label,
                skipped=True,
                skip_reason=f"already ran today ({already} time(s)); pass force=True to repeat",
                status="skipped",
            )

        # Figure out recipient.
        rec = _find_wallet(inputs.wallet_label)
        if rec.kind != "evm":
            raise SkillError(f"wallet '{rec.label}' is not EVM")
        to = inputs.to or rec.address

        # Jitter before broadcast (not before simulation).
        if inputs.jitter_seconds and not (inputs.simulate is True):
            await asyncio.sleep(random.uniform(0, inputs.jitter_seconds))

        # Delegate to the shared send skill.
        send = WalletSendSkill()
        out = await send.run(
            SendInput(
                chain_slug=inputs.chain_slug,
                wallet_label=inputs.wallet_label,
                to=to,
                amount_eth="0",
                simulate=inputs.simulate,
                wait_receipt=True,
            ),
            ctx,
        )

        # Only bump the idempotency counter if we actually broadcast.
        if not out.simulated and out.status in ("broadcast", "mined"):
            ep.bump_counter(counter_key)

        return DailyTxOutput(
            chain=inputs.chain_slug,
            wallet_label=inputs.wallet_label,
            skipped=False,
            tx_hash=out.tx_hash,
            status=out.status,
            explorer_url=out.explorer_url,
            simulated=out.simulated,
        )

    def summary(self, output: DailyTxOutput) -> str:
        if output.skipped:
            return f"{output.chain} daily_tx skipped: {output.skip_reason}"
        return (
            f"{output.chain} daily_tx [{output.status}] "
            f"wallet={output.wallet_label} tx={output.tx_hash or '-'}"
        )


def _find_wallet(label: str):
    for r in WalletStore().list_public():
        if r.label == label:
            return r
    raise SkillError(f"wallet not found: {label}")
