"""Solana RPC pool - just a thin wrapper for symmetry with EvmClientPool."""

from __future__ import annotations

from solana.rpc.api import Client
from solders.pubkey import Pubkey

from ..config import load_chains


class SolanaClientPool:
    def __init__(self) -> None:
        self._clients: dict[str, Client] = {}

    def reload(self) -> None:
        self._clients.clear()

    def get(self, slug: str) -> Client:
        if slug in self._clients:
            return self._clients[slug]
        chains = load_chains().chains
        if slug not in chains or chains[slug].kind != "solana":
            raise KeyError(f"unknown Solana chain: {slug}")
        url = chains[slug].rpc_urls[0]
        client = Client(url, timeout=15)
        self._clients[slug] = client
        return client

    def balance_lamports(self, slug: str, address: str) -> int:
        client = self.get(slug)
        resp = client.get_balance(Pubkey.from_string(address))
        return int(resp.value)

    def chain_slugs(self) -> list[str]:
        return [s for s, c in load_chains().chains.items() if c.kind == "solana"]
