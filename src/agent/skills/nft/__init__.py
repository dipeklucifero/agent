"""NFT skills (ERC-721 and ERC-1155).

ROADMAP:
  - nft.mint_erc721(chain_slug, contract, to, token_uri, wallet_label,
                    simulate=True) -> tx_hash
  - nft.mint_erc1155(chain_slug, contract, to, token_id, amount, data,
                     wallet_label, simulate=True) -> tx_hash
  - nft.deploy_collection(chain_slug, name, symbol, base_uri, wallet_label,
                          simulate=True) -> contract_address
  - nft.read_metadata(chain_slug, contract, token_id) -> metadata_json

Implementation notes:
  - Many mint endpoints are gated (merkle proof, signature). Make the mint
    function accept an optional ``extra_calldata`` hex string so Hermes can
    assemble it from context (pulled by research.fetch_url).
  - For ``mint_erc721`` prefer calling a known ``safeMint(address,uri)``
    signature; fall back to free-form calldata if the collection uses a
    non-standard mint selector.
"""
