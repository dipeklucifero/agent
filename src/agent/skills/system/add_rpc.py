"""Add or replace an RPC endpoint for a known chain, or register a new chain.

Autonomous self-development: the agent runs this when the owner says
"add a new Monad RPC" or "add chain Foo with these endpoints".
"""

from __future__ import annotations

import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field, HttpUrl

from ...config import Chain, ChainsConfig, load_chains, load_policies, save_chains
from ..base import Skill, SkillContext, SkillDenied, SkillError

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class AddRpcInput(BaseModel):
    slug: str = Field(
        ..., description="Stable chain identifier, snake_case (e.g. 'monad_testnet')."
    )
    rpc_url: HttpUrl = Field(..., description="The new RPC URL to add.")
    # Creation-time fields (required if `slug` doesn't already exist).
    kind: Literal["evm", "solana"] | None = Field(
        default=None, description="Required only when registering a new chain."
    )
    name: str | None = Field(default=None, description="Human-readable name.")
    is_testnet: bool | None = None
    chain_id: int | None = Field(default=None, description="EVM chain id.")
    native_symbol: str | None = None
    explorer: str | None = None
    # Behaviour toggles.
    make_primary: bool = Field(
        default=False,
        description="If true, the new URL is inserted at the top of rpc_urls.",
    )
    verify: bool = Field(
        default=True,
        description="If true, probe the endpoint before committing.",
    )


class AddRpcOutput(BaseModel):
    slug: str
    created_chain: bool
    rpc_urls: list[str]
    verified: bool
    verification_note: str = ""


class AddRpcSkill(Skill):
    name = "system.add_rpc"
    family = "system"
    description = (
        "Add a new RPC endpoint to an existing chain, or register a brand-new "
        "chain in config/chains.yaml. Optionally verifies the endpoint by "
        "calling eth_chainId (EVM) or getVersion (Solana) before saving."
    )
    Input = AddRpcInput
    Output = AddRpcOutput
    touches_filesystem = True

    async def run(self, inputs: AddRpcInput, ctx: SkillContext) -> AddRpcOutput:
        if not load_policies().self_dev.allow_add_rpc:
            raise SkillDenied("add_rpc disabled by policy")
        if not _SLUG_RE.match(inputs.slug):
            raise SkillError(f"invalid slug: {inputs.slug!r}")

        cfg: ChainsConfig = load_chains()
        url = str(inputs.rpc_url)
        created = False

        if inputs.slug in cfg.chains:
            chain = cfg.chains[inputs.slug]
            if url in chain.rpc_urls:
                return AddRpcOutput(
                    slug=inputs.slug,
                    created_chain=False,
                    rpc_urls=chain.rpc_urls,
                    verified=False,
                    verification_note="URL already present; nothing to do.",
                )
            if inputs.make_primary:
                chain.rpc_urls = [url, *chain.rpc_urls]
            else:
                chain.rpc_urls = [*chain.rpc_urls, url]
        else:
            # Creating a new chain requires the full set of fields.
            missing = [
                f for f in ("kind", "name", "is_testnet")
                if getattr(inputs, f) is None
            ]
            if inputs.kind == "evm" and inputs.chain_id is None:
                missing.append("chain_id")
            if missing:
                raise SkillError(
                    f"chain {inputs.slug!r} is new; missing fields: {missing}"
                )
            chain = Chain(
                kind=inputs.kind,  # type: ignore[arg-type]
                name=inputs.name or inputs.slug,
                is_testnet=bool(inputs.is_testnet),
                chain_id=inputs.chain_id,
                rpc_urls=[url],
                explorer=inputs.explorer or "",
                native_symbol=inputs.native_symbol or "",
            )
            cfg.chains[inputs.slug] = chain
            created = True

        verified = False
        note = ""
        if inputs.verify:
            verified, note = await _probe(url, chain.kind, chain.chain_id)
            if not verified:
                raise SkillError(f"RPC verification failed: {note}")

        save_chains(cfg)
        _reload_pools(ctx)
        return AddRpcOutput(
            slug=inputs.slug,
            created_chain=created,
            rpc_urls=chain.rpc_urls,
            verified=verified,
            verification_note=note,
        )

    def summary(self, output: AddRpcOutput) -> str:
        verb = "registered new chain" if output.created_chain else "added RPC to"
        return f"{verb} '{output.slug}'; endpoints: {output.rpc_urls}"


async def _probe(url: str, kind: str, expected_chain_id: int | None) -> tuple[bool, str]:
    """Quick liveness check for an RPC endpoint. 5s budget."""
    async with httpx.AsyncClient(timeout=5.0) as http:
        try:
            if kind == "evm":
                r = await http.post(
                    url,
                    json={"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1},
                )
                r.raise_for_status()
                data = r.json()
                if "result" not in data:
                    return False, f"no result field: {data}"
                got = int(data["result"], 16)
                if expected_chain_id is not None and got != expected_chain_id:
                    return False, f"chain id mismatch: got {got}, expected {expected_chain_id}"
                return True, f"eth_chainId -> {got}"
            else:  # solana
                r = await http.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "getVersion"},
                )
                r.raise_for_status()
                data = r.json()
                if "result" not in data:
                    return False, f"no result field: {data}"
                return True, f"getVersion -> {data['result']}"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"


def _reload_pools(ctx: SkillContext) -> None:
    """Drop cached Web3 clients so the new RPC takes effect immediately."""
    if not ctx.extras:
        return
    for key in ("evm_pool", "solana_pool"):
        pool = ctx.extras.get(key)
        if pool is not None and hasattr(pool, "reload"):
            pool.reload()
