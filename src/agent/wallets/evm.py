"""EVM wallet helpers - thin wrapper around eth_account."""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account

# eth_account's HD wallet features are opt-in and require a mnemonic flag.
Account.enable_unaudited_hdwallet_features()


@dataclass
class NewEvmWallet:
    address: str          # EIP-55 checksum
    private_key: bytes    # 32 bytes, raw


def create_evm_wallet() -> NewEvmWallet:
    """Generate a fresh random EVM wallet. No mnemonic - burner style."""
    acct = Account.create()
    return NewEvmWallet(address=acct.address, private_key=acct.key)


def address_from_key(private_key: bytes) -> str:
    return Account.from_key(private_key).address
