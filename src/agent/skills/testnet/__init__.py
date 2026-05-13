"""Testnet farming skills.

ROADMAP:
  - testnet.faucet_claim(chain_slug, wallet_label, faucet_url=None) -> status
      Many faucets are Cloudflare-gated. Either use the chain's official
      JSON API (Sepolia, Base Sepolia have open faucets) or ask the user
      to solve captcha once and cache the cookie under data/faucet_sessions/.
  - testnet.daily_tx(chain_slug, wallet_label, to=None, amount_eth=0)
      -> tx_hash. The bread-and-butter farming action: send ~0 to a contract
      or self to tick a daily. Uses a jittered delay.
  - testnet.bridge(from_chain, to_chain, amount, wallet_label, simulate=True)
      Start with official bridge contracts only (Base, OP Sepolia). No
      third-party bridges - too many rug/scam vectors.
  - testnet.swap_uniswap_v3(chain_slug, token_in, token_out, amount_in,
                            wallet_label, simulate=True) -> tx_hash

Implementation notes:
  - All chain-mutating skills set mutates_chain=True => simulate-first by
    policy.
  - Use scheduler.schedule_skill() to cron these (e.g., '0 9 * * *' UTC).
"""
