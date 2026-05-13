"""Send native ETH (or compatible) on any configured EVM chain.

This is the first chain-mutating skill. It exercises the full sign path:
  1. Resolve wallet + chain.
  2. Build a typed tx (EIP-1559 if supported, else legacy).
  3. Pre-flight: eth_estimateGas + eth_call for a dry run.
  4. If simulate=True -> return the would-be tx hash=None plus estimate.
  5. Otherwise unlock keystore, sign, broadcast, optionally wait for receipt.

Private key is materialised only inside ``WalletStore.unlock()`` and never
crosses an LLM boundary. The skill returns the address, tx hash, and gas
metadata only.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from eth_account import Account
from pydantic import BaseModel, Field
from web3 import Web3

from ...config import load_chains
from ...wallets import WalletStore
from ..base import Skill, SkillContext, SkillError


class SendInput(BaseModel):
    chain_slug: str = Field(..., description="Chain key from chains.yaml, e.g. 'base_sepolia'.")
    wallet_label: str = Field(..., description="Sender wallet label.")
    to: str = Field(..., description="Recipient EVM address (0x...).")
    amount_eth: str = Field(
        default="0",
        description=(
            "Amount to send as a decimal ETH string (e.g. '0.001'). "
            "Use '0' for a zero-value self-tx / daily tick."
        ),
    )
    data: str = Field(
        default="0x",
        description="Optional calldata hex. Default 0x (plain transfer).",
    )
    gas_limit: int | None = Field(
        default=None,
        description="Optional manual gas limit. If omitted, uses eth_estimateGas * 1.2.",
    )
    simulate: bool | None = Field(
        default=None,
        description=(
            "If true, dry-run via eth_call + eth_estimateGas and do NOT broadcast. "
            "Policy forces this to true unless owner explicitly said otherwise."
        ),
    )
    wait_receipt: bool = Field(
        default=True,
        description="Wait for the tx to be mined (timeout 90s) and include receipt info.",
    )


class SendOutput(BaseModel):
    chain: str
    from_address: str
    to: str
    amount_eth: str
    value_wei: str
    gas_limit: int
    max_fee_per_gas_gwei: str | None = None
    max_priority_fee_per_gas_gwei: str | None = None
    gas_price_gwei: str | None = None
    estimated_cost_eth: str
    simulated: bool
    tx_hash: str | None = None
    block_number: int | None = None
    status: str  # "simulated" | "broadcast" | "mined" | "failed"
    explorer_url: str | None = None


class WalletSendSkill(Skill):
    name = "wallet_send"
    family = "wallet"
    description = (
        "Send native token on an EVM chain. Supports simulate-first (dry run). "
        "Uses a burner wallet by label; never reveals private keys."
    )
    Input = SendInput
    Output = SendOutput
    mutates_chain = True

    async def run(self, inputs: SendInput, ctx: SkillContext) -> SendOutput:
        chains = load_chains().chains
        chain = chains.get(inputs.chain_slug)
        if chain is None or chain.kind != "evm":
            raise SkillError(f"unknown EVM chain: {inputs.chain_slug}")

        pool = (ctx.extras or {}).get("evm_pool")
        if pool is None:
            raise SkillError("EVM pool not available in skill context")

        # Resolve wallet (public info only at this point).
        rec = _find_wallet(inputs.wallet_label)
        if rec.kind != "evm":
            raise SkillError(f"wallet '{rec.label}' is {rec.kind}, not evm")
        sender = rec.address
        to_addr = Web3.to_checksum_address(inputs.to)
        value_wei = _eth_to_wei(inputs.amount_eth)

        simulate = True if inputs.simulate is None else bool(inputs.simulate)

        # Everything web3 is sync; push to a thread so we don't block the loop.
        def _build_and_maybe_send() -> dict[str, Any]:
            w3 = pool.get(inputs.chain_slug)
            nonce = w3.eth.get_transaction_count(sender, "pending")

            tx: dict[str, Any] = {
                "from": sender,
                "to": to_addr,
                "value": value_wei,
                "data": inputs.data,
                "nonce": nonce,
                "chainId": chain.chain_id,
            }

            # EIP-1559 vs legacy: probe the pending block.
            fee_meta: dict[str, Any] = {}
            use_1559 = False
            try:
                pending = w3.eth.get_block("pending")
                base_fee = pending.get("baseFeePerGas")
                if base_fee is not None:
                    use_1559 = True
                    # Conservative: priority ~1 gwei, max = 2*base + priority.
                    priority = w3.to_wei("1", "gwei")
                    try:
                        priority = w3.eth.max_priority_fee or priority
                    except Exception:  # noqa: BLE001
                        pass
                    max_fee = base_fee * 2 + priority
                    tx["maxFeePerGas"] = max_fee
                    tx["maxPriorityFeePerGas"] = priority
                    tx["type"] = 2
                    fee_meta["max_fee_per_gas_gwei"] = _wei_to_gwei(max_fee)
                    fee_meta["max_priority_fee_per_gas_gwei"] = _wei_to_gwei(priority)
            except Exception:  # noqa: BLE001
                pass

            if not use_1559:
                gas_price = w3.eth.gas_price
                tx["gasPrice"] = gas_price
                fee_meta["gas_price_gwei"] = _wei_to_gwei(gas_price)

            # Dry-run: eth_call surfaces revert reasons without spending gas.
            # Skip the 'from' field check - some nodes reject value on call.
            call_tx = {k: v for k, v in tx.items() if k in ("from", "to", "data", "value")}
            try:
                w3.eth.call(call_tx)
            except Exception as e:  # noqa: BLE001
                raise SkillError(f"simulation reverted: {e}") from e

            # Estimate gas; leave 20% headroom.
            try:
                estimated = w3.eth.estimate_gas(call_tx)
            except Exception as e:  # noqa: BLE001
                raise SkillError(f"gas estimation failed: {e}") from e
            gas_limit = int(inputs.gas_limit or int(estimated * 1.2))
            tx["gas"] = gas_limit
            fee_meta["gas_limit"] = gas_limit

            # Cost projection
            if use_1559:
                gas_cost_wei = tx["maxFeePerGas"] * gas_limit
            else:
                gas_cost_wei = tx["gasPrice"] * gas_limit
            fee_meta["estimated_cost_eth"] = _wei_to_eth(gas_cost_wei + value_wei)

            if simulate:
                fee_meta["simulated"] = True
                fee_meta["tx_hash"] = None
                fee_meta["block_number"] = None
                fee_meta["status"] = "simulated"
                return fee_meta

            # Sign + broadcast. Key stays in unlock() scope.
            with WalletStore().unlock(rec.label) as pk:
                signed = Account.sign_transaction(tx, pk)
            raw = signed.raw_transaction if hasattr(signed, "raw_transaction") else signed.rawTransaction
            tx_hash = w3.eth.send_raw_transaction(raw)
            fee_meta["simulated"] = False
            fee_meta["tx_hash"] = tx_hash.hex()
            fee_meta["status"] = "broadcast"

            if inputs.wait_receipt:
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
                    fee_meta["block_number"] = int(receipt["blockNumber"])
                    fee_meta["status"] = "mined" if receipt["status"] == 1 else "failed"
                except Exception as e:  # noqa: BLE001
                    fee_meta["status"] = f"pending (wait failed: {e})"
            return fee_meta

        meta = await asyncio.to_thread(_build_and_maybe_send)

        explorer = None
        if chain.explorer and meta.get("tx_hash"):
            explorer = f"{chain.explorer.rstrip('/')}/tx/{meta['tx_hash']}"

        return SendOutput(
            chain=inputs.chain_slug,
            from_address=sender,
            to=to_addr,
            amount_eth=inputs.amount_eth,
            value_wei=str(value_wei),
            gas_limit=int(meta.get("gas_limit", 0)),
            max_fee_per_gas_gwei=meta.get("max_fee_per_gas_gwei"),
            max_priority_fee_per_gas_gwei=meta.get("max_priority_fee_per_gas_gwei"),
            gas_price_gwei=meta.get("gas_price_gwei"),
            estimated_cost_eth=meta.get("estimated_cost_eth", "0"),
            simulated=meta.get("simulated", simulate),
            tx_hash=meta.get("tx_hash"),
            block_number=meta.get("block_number"),
            status=meta.get("status", "unknown"),
            explorer_url=explorer,
        )

    def summary(self, output: SendOutput) -> str:
        if output.simulated:
            return (
                f"[SIMULATED] {output.chain}: {output.from_address} -> {output.to} "
                f"value={output.amount_eth} ETH, est cost={output.estimated_cost_eth} ETH"
            )
        return (
            f"[{output.status}] {output.chain}: {output.amount_eth} ETH "
            f"-> {output.to}, tx={output.tx_hash}"
        )


# -------- helpers ---------------------------------------------------------


def _find_wallet(label: str):
    for r in WalletStore().list_public():
        if r.label == label:
            return r
    raise SkillError(f"wallet not found: {label}")


def _eth_to_wei(amount: str) -> int:
    # Use Decimal so '0.0001' doesn't become a float.
    return int(Decimal(str(amount)) * Decimal(10**18))


def _wei_to_eth(wei: int) -> str:
    if wei == 0:
        return "0"
    d = Decimal(wei) / Decimal(10**18)
    return (f"{d:.18f}".rstrip("0").rstrip(".")) or "0"


def _wei_to_gwei(wei: int) -> str:
    if wei == 0:
        return "0"
    d = Decimal(wei) / Decimal(10**9)
    return (f"{d:.9f}".rstrip("0").rstrip(".")) or "0"
