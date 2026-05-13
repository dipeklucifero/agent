"""Fungible token skills (ERC-20).

ROADMAP:
  - token.deploy_erc20(chain_slug, name, symbol, initial_supply, wallet_label,
                       simulate=True) -> contract_address, tx_hash
  - token.transfer(chain_slug, token_address, to, amount, wallet_label,
                   simulate=True) -> tx_hash
  - token.approve(chain_slug, token_address, spender, amount, wallet_label,
                  simulate=True) -> tx_hash
  - token.mint(chain_slug, token_address, to, amount, wallet_label,
               simulate=True) -> tx_hash   # only if token has a mint role

Implementation notes:
  - Reuse WalletStore().unlock(label) to sign, never expose the key.
  - For deploy, ship a minimal OpenZeppelin-style ERC20 bytecode + ABI as
    a constant in a sibling ``_abis.py`` to avoid a runtime solc dependency.
  - Set mutates_chain=True so PolicyEngine auto-injects simulate=True.
"""
