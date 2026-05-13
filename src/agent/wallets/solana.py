"""Solana wallet helpers - thin wrapper around solders.Keypair."""

from __future__ import annotations

from dataclasses import dataclass

from solders.keypair import Keypair


@dataclass
class NewSolanaWallet:
    address: str          # base58 public key
    private_key: bytes    # 64 bytes (ed25519 secret + public)


def create_solana_wallet() -> NewSolanaWallet:
    kp = Keypair()
    return NewSolanaWallet(address=str(kp.pubkey()), private_key=bytes(kp))


def address_from_key(private_key: bytes) -> str:
    return str(Keypair.from_bytes(private_key).pubkey())
