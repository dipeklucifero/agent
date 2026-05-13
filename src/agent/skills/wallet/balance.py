"""Read native-token balances for a wallet across one or many chains.

This is the pipeline's 'hello world': pure read, no signing, exercises
config -> keystore -> RPC pool -> skill-framework end-to-end.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from pydantic import BaseModel, Field

from ...config import load_chains
from ...wallets import WalletStore
from ..base import Skill, SkillContext, SkillError


class BalanceInput(BaseModel):
    wallet_label: str | None = Field(
        default=None,
        description=(
            "Wallet label from system_list_wallets. If omitted, `address` must "
            "be provided. Use label for burner wallets, address for anyone else."
        ),
    )
    address: str | None = Field(
        default=None,
        description="Explicit address. Takes precedence over wallet_label.",
    )
    chain_slugs: list[str] | None = Field(
        default=None,
        description=(
            "Which chains to query. If omitted, queries all chains of the "
            "wallet's kind (EVM or Solana)."
        ),
    )


class ChainBalance(BaseModel):
    chain: str
    symbol: str
    balance: str    # human-readable decimal
    raw: str        # base-unit integer as string (wei / lamports)


class BalanceOutput(BaseModel):
    address: str
    kind: str
    results: list[ChainBalance]
    errors: dict[str, str] = Field(default_factory=dict)


class BalanceSkill(Skill):
    name = "wallet_balance"
    family = "wallet"
    description = (
        "Read native-token balance for a wallet across one or more chains. "
        "Read-only. Use wallet_label for burner wallets, or address for any "
        "external address."
    )
    Input = BalanceInput
    Output = BalanceOutput

    async def run(self, inputs: BalanceInput, ctx: SkillContext) -> BalanceOutput:
        if not inputs.wallet_label and not inputs.address:
            raise SkillError("provide wallet_label or address")

        # Figure out address + kind
        if inputs.wallet_label:
            rec = _find_wallet(inputs.wallet_label)
            address, kind = rec.address, rec.kind
        else:
            address = inputs.address  # type: ignore[assignment]
            kind = _infer_kind(address)

        chains = load_chains().chains
        slugs = inputs.chain_slugs or [
            s for s, c in chains.items() if c.kind == kind
        ]

        # Resolve pools lazily from ctx.extras
        evm_pool = (ctx.extras or {}).get("evm_pool")
        sol_pool = (ctx.extras or {}).get("solana_pool")

        results: list[ChainBalance] = []
        errors: dict[str, str] = {}

        async def one(slug: str) -> None:
            chain = chains.get(slug)
            if chain is None:
                errors[slug] = "unknown chain"
                return
            try:
                if chain.kind == "evm" and evm_pool is not None:
                    raw = await asyncio.to_thread(evm_pool.balance_wei, slug, address)
                    human = _wei_to_eth(raw)
                    results.append(
                        ChainBalance(
                            chain=slug, symbol=chain.native_symbol or "ETH",
                            balance=human, raw=str(raw),
                        )
                    )
                elif chain.kind == "solana" and sol_pool is not None:
                    raw = await asyncio.to_thread(sol_pool.balance_lamports, slug, address)
                    human = _lamports_to_sol(raw)
                    results.append(
                        ChainBalance(
                            chain=slug, symbol=chain.native_symbol or "SOL",
                            balance=human, raw=str(raw),
                        )
                    )
                else:
                    errors[slug] = f"no pool for kind={chain.kind}"
            except Exception as e:  # noqa: BLE001
                errors[slug] = f"{type(e).__name__}: {e}"

        # Parallelise across chains; RPCs are the latency bottleneck.
        await asyncio.gather(*(one(s) for s in slugs))
        # Deterministic order for the LLM.
        results.sort(key=lambda r: r.chain)
        return BalanceOutput(address=address, kind=kind, results=results, errors=errors)

    def summary(self, output: BalanceOutput) -> str:
        if not output.results:
            return f"{output.address}: no balances (errors: {output.errors})"
        parts = [f"{r.chain}={r.balance} {r.symbol}" for r in output.results]
        return f"{output.address}: " + ", ".join(parts)


def _find_wallet(label: str):
    for r in WalletStore().list_public():
        if r.label == label:
            return r
    raise SkillError(f"wallet not found: {label}")


def _infer_kind(address: str) -> str:
    if address.startswith("0x") and len(address) == 42:
        return "evm"
    # Solana base58 keys are 32-44 chars, no 0x prefix.
    return "solana"


def _wei_to_eth(wei: int) -> str:
    """Fixed-point decimal, no scientific notation. 18 decimals."""
    if wei == 0:
        return "0"
    d = Decimal(wei) / Decimal(10**18)
    s = f"{d:.18f}".rstrip("0").rstrip(".")
    return s or "0"


def _lamports_to_sol(lamports: int) -> str:
    if lamports == 0:
        return "0"
    d = Decimal(lamports) / Decimal(10**9)
    s = f"{d:.9f}".rstrip("0").rstrip(".")
    return s or "0"
