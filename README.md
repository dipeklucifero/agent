# Hermes Agent

A personal Telegram-controlled AI agent powered by Hermes (via OpenRouter) for
Web3 operations and social automation. Skills-based architecture with
self-development hooks: the agent can add its own RPCs, create its own wallets,
and propose new skills for your approval.

## Architecture

```
Telegram <-> agent loop <-> Hermes (OpenRouter)
                |
                +-- Soul (persona + principles)
                +-- Policy (pre-tool guardrails, tx caps)
                +-- Memory (working / episodic / tasks - SQLite)
                +-- Scheduler (APScheduler, SQLite jobstore)
                +-- Skills registry
                     |-- system/   # self-development (add rpc, new wallet, ...)
                     |-- wallet/   # balances, sends (gated)
                     |-- nft/ token/ testnet/   (stubs to extend)
                     |-- x/ discord/            (stubs to extend)
```

## Quickstart

```bash
cp .env.example .env   # fill in keys
mkdir -p data
docker compose build
docker compose up -d
docker compose logs -f
```

Open Telegram, DM your bot, send `/start`.

## Self-development scope

**Safe & autonomous (agent can just do):**
- `add_rpc` — add/swap RPC endpoints in `config/chains.yaml`
- `create_wallet` — generate fresh EVM or Solana wallet, store encrypted
- `list_wallets` — enumerate burner wallets
- `add_contact` — add labelled address to address book

**Gated (agent drafts, you approve):**
- `propose_skill` — writes a spec to `skills/proposed/<name>.md` and DMs you.
  Actual code generation happens in a separate conversation with Kiro or your
  editor of choice. The agent never auto-loads untrusted Python.

## Security model

- Private keys are AES-256-GCM encrypted with a key derived from
  `KEYSTORE_PASSWORD` via scrypt. Keys never leave the tool handlers.
- The LLM sees addresses, balances, and tx hashes — never private keys.
- Every tool call is logged to SQLite and (optionally) mirrored to a
  Telegram audit channel.
- Telegram messages are only accepted from `TELEGRAM_OWNER_ID`.
- Every tx-producing skill supports `simulate=True` by default.
- Mainnet txs require explicit `CONFIRM MAINNET` string in the same turn.

## Extending

Drop a new file in `src/agent/skills/<category>/<name>.py` following the
`Skill` ABC in `skills/base.py`. The registry auto-discovers it.
