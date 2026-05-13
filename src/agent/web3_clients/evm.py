"""EVM RPC client pool with per-chain failover.

Responsibilities:
  * Lazily build a ``Web3`` instance for each configured chain id.
  * Cycle through ``rpc_urls`` on connection failure.
  * Expose a small typed surface used by skills (``balance``, ``chain_id``,
    ``get_block``). Keep this file thin; skills layer does anything richer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from web3 import Web3
from web3.exceptions import Web3Exception
from web3.middleware import ExtraDataToPOAMiddleware

from ..config import Chain, load_chains


class UnknownChainError(KeyError):
    pass


@dataclass
class _ChainClient:
    chain: Chain
    w3: Web3


class EvmClientPool:
    """Keyed by chain *slug* (the key in ``chains.yaml``), not chain id.

    Slugs are stable & human-readable. Multiple slugs can share a chain id
    (e.g., a fork), so we deliberately don't index by id.
    """

    def __init__(self) -> None:
        self._clients: dict[str, _ChainClient] = {}

    def reload(self) -> None:
        """Drop cached clients so next access re-reads chains.yaml."""
        self._clients.clear()

    def _iter_evm_chains(self) -> Iterable[tuple[str, Chain]]:
        for slug, chain in load_chains().chains.items():
            if chain.kind == "evm":
                yield slug, chain

    def get(self, slug: str) -> Web3:
        if slug in self._clients:
            return self._clients[slug].w3
        chains = dict(self._iter_evm_chains())
        if slug not in chains:
            raise UnknownChainError(f"unknown EVM chain: {slug}")
        chain = chains[slug]
        w3 = self._build(chain)
        self._clients[slug] = _ChainClient(chain=chain, w3=w3)
        return w3

    def _build(self, chain: Chain) -> Web3:
        last_exc: Exception | None = None
        for url in chain.rpc_urls:
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
                # Many L2s/testnets emit extra `extraData` that breaks the
                # default PoA-less middleware. Harmless to add everywhere.
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    return w3
            except (Web3Exception, Exception) as e:  # noqa: BLE001
                last_exc = e
                continue
        raise ConnectionError(
            f"no working RPC for chain {chain.name!r}: {last_exc}"
        )

    # ---- convenience -----------------------------------------------------
    def balance_wei(self, slug: str, address: str) -> int:
        w3 = self.get(slug)
        checksum = Web3.to_checksum_address(address)
        return int(w3.eth.get_balance(checksum))

    def chain_slugs(self) -> list[str]:
        return [slug for slug, _ in self._iter_evm_chains()]

    def describe(self, slug: str) -> Chain:
        chain = load_chains().chains.get(slug)
        if chain is None or chain.kind != "evm":
            raise UnknownChainError(slug)
        return chain
