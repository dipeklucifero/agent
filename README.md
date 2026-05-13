# Hermes Agent

A personal, Telegram-controlled AI agent for Web3 operations and social
automation, powered by [Nous Research Hermes](https://nousresearch.com) via
[OpenRouter](https://openrouter.ai). Skills-based, self-extending, and
tuned to run on a modest VPS.

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-alpha-orange">
  <img alt="Style" src="https://img.shields.io/badge/style-ruff-black">
</p>

---

## Table of contents

- [Why](#why)
- [Architecture](#architecture)
- [Skills catalogue](#skills-catalogue)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Self-development](#self-development)
- [Security model](#security-model)
- [Scheduling](#scheduling)
- [Telegram commands](#telegram-commands)
- [Development](#development)
- [Extending](#extending)
- [Operational notes](#operational-notes)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why

Most Web3 "farming" workflows are repetitive, error-prone, and easy to
automate: claim a faucet, send a daily self-tx, mint a testnet NFT, follow
an account on X, join a Discord. Hermes Agent wraps those into typed,
policy-gated **skills** that a Telegram chat can drive safely.

Design goals, in priority order:

1. **Safety over cleverness.** Simulate-first; mainnet requires an explicit
   confirmation string; private keys never cross an LLM boundary.
2. **Auditable by default.** Every skill call is logged to SQLite and
   optionally mirrored to a Telegram audit channel.
3. **Self-extensible.** The agent can add RPCs, create burner wallets,
   update its own preferences, and draft specs for new skills. Code changes
   still require a human review.
4. **Cheap to run.** Fits on a 2 vCPU / 2 GB RAM VPS. No GPU required; the
   LLM lives at OpenRouter.

---

## Architecture

```
                ┌────────────────────┐
                │   Telegram (DM)    │  owner-only
                └─────────┬──────────┘
                          │
                          ▼
         ┌────────────────────────────────┐
         │   HermesAgent (llm.py)         │
         │   ── tool-calling loop ────    │
         │   Hermes 4 -> Hermes 3 fallback│
         └───────┬──────────────┬─────────┘
                 │              │
        system prompt        tool_calls
        (soul.py)               │
                 │              ▼
     ┌───────────┴──────┐  ┌──────────────────┐
     │   Soul / Policy  │  │   Skill registry │
     │   (YAML-backed)  │  │  (auto-discover) │
     └──────────────────┘  └────────┬─────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                ▼         ▼            ▼             ▼
    ┌────────┐      ┌─────────┐ ┌───────┐  ┌──────────┐   ┌─────────┐
    │ system │      │ wallet  │ │ nft   │  │ testnet  │   │ research│
    │ add_rpc│      │ balance │ │ ...   │  │ daily_tx │   │ notes_* │
    │ ...    │      │ send    │ │       │  │ ...      │   │         │
    └────────┘      └─────────┘ └───────┘  └──────────┘   └─────────┘
                          │                      │
                          ▼                      ▼
                 ┌──────────────┐       ┌──────────────────┐
                 │  Keystore    │       │   RPC pools      │
                 │  AES-256-GCM │       │   EVM / Solana   │
                 │  scrypt KDF  │       │   with failover  │
                 └──────────────┘       └──────────────────┘
                          │
                          ▼
                 ┌───────────────────────────────┐
                 │         SQLite (WAL)          │
                 │   episodic | tasks | notes    │
                 │   counters | scheduler jobs   │
                 └───────────────────────────────┘
```

| Layer | Module | Notes |
|-------|--------|-------|
| Interface | `interfaces/telegram_bot.py` | python-telegram-bot, owner-locked |
| LLM | `llm.py` | OpenRouter, OpenAI-compatible tool-calling |
| Soul | `soul.py`, `config/soul.yaml` | Persona + preferences, re-read each turn |
| Policy | `policy.py`, `config/policies.yaml` | Kill switches, simulate-first, mainnet confirm |
| Skills | `skills/` | ABC + auto-discovering registry |
| Wallets | `wallets/`, `config/chains.yaml` | AES-256-GCM keystore, chain metadata |
| Memory | `memory/` | Episodic, tasks, notes (FTS5), counters |
| Scheduler | `scheduler.py` | APScheduler with SQLite jobstore |
| RPC | `web3_clients/` | EVM + Solana pools, URL failover |

---

## Skills catalogue

Skill names use `category_action` (underscore) — required by the
OpenAI-compatible function-calling spec.

### system — self-development

| Skill | Purpose |
|-------|---------|
| `system_list_wallets` | Enumerate burner wallets (public info only). |
| `system_create_wallet` | Generate a fresh EVM or Solana wallet, persist encrypted. |
| `system_add_rpc` | Add an RPC endpoint to an existing chain or register a new chain. Probes the endpoint before committing. |
| `system_add_contact` | Append a labelled address to the contacts book. |
| `system_update_preferences` | Update soft preferences in `soul.yaml` (allowlist only). |
| `system_propose_skill` | Draft a markdown spec for a new skill (never auto-executed). |

### wallet

| Skill | Purpose |
|-------|---------|
| `wallet_balance` | Native-token balance across one or many chains, parallelised. |
| `wallet_send` | Sign and broadcast a native transfer. EIP-1559 or legacy. `simulate=True` by default. |

### testnet

| Skill | Purpose |
|-------|---------|
| `testnet_daily_tx` | Self-tx ticker for daily activity streaks. Idempotent per day. Refuses mainnet. |

### research

| Skill | Purpose |
|-------|---------|
| `notes_add` | Persist a free-form note with an optional tag. |
| `notes_search` | Full-text search over notes (SQLite FTS5). |

### Stubs with roadmaps

Each of the following packages has a module docstring describing the
planned skills; contributions welcome. The agent will not expose them
to the LLM until classes are implemented.

- `nft/` — ERC-721 / ERC-1155 mint, deploy collection, read metadata.
- `token/` — ERC-20 deploy, transfer, approve, mint (role-based).
- `x/` — Twikit-based follow / like / retweet / post on a burner account.
- `discord/` — Official bot messaging in servers you control.
- `telegram_ops/` — Telethon userbot for group-join / DM tasks.

---

## Quick start

### Prerequisites

- A Linux VPS (tested on 2 vCPU / 2 GB RAM / 40 GB disk).
- [Docker](https://docs.docker.com/engine/install/) and Docker Compose v2.
- A Telegram bot token from [@BotFather](https://t.me/BotFather) and your
  numeric user id from [@userinfobot](https://t.me/userinfobot).
- An OpenRouter API key (free tier is fine to start).

### Install

```bash
git clone https://github.com/dipeklucifero/agent.git hermes-agent
cd hermes-agent
cp .env.example .env
$EDITOR .env           # fill in the required values
mkdir -p data
docker compose build
docker compose up -d
docker compose logs -f
```

Open Telegram, DM your bot, send `/start`.

### Smoke test

```
You:    /help
Agent:  (lists the skill catalogue)

You:    create a fresh EVM burner wallet
Agent:  created evm wallet 'burner-evm-1' -> 0xAbC...

You:    show its balance on all testnets
Agent:  0xAbC...: base_sepolia=0 ETH, ethereum_sepolia=0 ETH, ...
```

---

## Configuration

Configuration lives in two places, both read on every turn:

- **Environment** (`.env`) — secrets and connection settings.
- **YAML files** (`config/`) — persona, chains, contacts, policies.
  Some of these are **agent-editable** via skills; the rest are owner-only.

### Environment variables

| Variable | Required | Purpose |
|----------|:---:|---------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter credential. |
| `HERMES_MODEL` | No | Default `nousresearch/hermes-4-70b`. |
| `HERMES_FALLBACK_MODEL` | No | Used when the primary errors; default `hermes-3-llama-3.1-8b`. |
| `TELEGRAM_BOT_TOKEN` | Yes | @BotFather token. |
| `TELEGRAM_OWNER_ID` | Yes | Numeric Telegram user id. Only this user is accepted. |
| `TELEGRAM_AUDIT_CHAT_ID` | No | Private channel id that mirrors every tool call. |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | No | Telethon userbot (required for `telegram_ops`). |
| `KEYSTORE_PASSWORD` | Yes | Derives the AES key for private-key encryption. |
| `X_USERNAME` / `X_EMAIL` / `X_PASSWORD` | No | Burner X account credentials. |
| `DISCORD_BOT_TOKEN` | No | For `discord` skills. |

### YAML files

| File | Editable by agent? | What it controls |
|------|:---:|------------------|
| `config/soul.yaml` | `preferences` only | Persona, principles, soft preferences. |
| `config/chains.yaml` | Yes | RPC endpoints, chain ids, testnet flags. |
| `config/contacts.yaml` | Yes | Labelled address book. |
| `config/policies.yaml` | **No** | Kill switches, tx caps, simulate-first, confirm strings. |

---

## Self-development

The agent has a bounded self-development scope. What it can do **without
asking** (subject to per-skill caps):

- Add or swap an RPC endpoint, register a new chain.
- Generate fresh burner wallets (capped per day).
- Add contacts to the address book.
- Update its own soft preferences within an allowlist.

What it **cannot** do on its own:

- Edit `principles` or `guardrails` in `soul.yaml`.
- Raise `tx_limits` in `policies.yaml`.
- Write executable Python.
- Auto-load any code.

For new skills, the agent calls `system_propose_skill`, which writes a
markdown specification to `data/skills_proposed/`. Code generation then
happens in a separate, reviewable workflow (your editor, a Kiro session,
a PR).

---

## Security model

- **Private keys are AES-256-GCM encrypted at rest.** The key is derived
  from `KEYSTORE_PASSWORD` via scrypt (`N=2^15, r=8, p=1`) with a
  per-wallet salt. The label is used as AES-GCM associated data, so
  copying a keystore file to a different label breaks decryption.
- **Keys never reach the LLM.** Signing happens inside a
  `WalletStore.unlock()` context that wipes the buffer on exit.
- **Owner-only Telegram.** Messages from any Telegram id other than
  `TELEGRAM_OWNER_ID` are silently dropped.
- **Simulate-first.** Every chain-mutating skill has `mutates_chain=True`.
  The policy layer injects `simulate=True` unless the caller set it
  explicitly.
- **Mainnet confirmation.** Broadcasting on any chain where
  `is_testnet=false` requires the string `CONFIRM MAINNET` in the same
  user turn. Read-only operations bypass this check.
- **Per-family kill switch.** `/disable <family>` removes a whole family
  of skills from the tool list until `/enable` reverses it.
- **Auditable.** Every tool invocation is appended to SQLite with status,
  inputs, output summary, and optional tx hash. Optional mirror to a
  Telegram audit channel.

Threats explicitly **out of scope**:

- A compromised VPS can read `data/` and extract the keystore plus
  `KEYSTORE_PASSWORD`. Treat the VPS as a burner machine.
- A malicious contract can drain funds you signed to interact with; this
  is not unique to agents.
- OpenRouter or upstream model providers see your prompts and skill
  outputs. Do not paste data you aren't willing to send.

---

## Scheduling

`AgentScheduler` is an APScheduler `AsyncIOScheduler` backed by a SQLite
job store, so scheduled skills survive restarts. Register a job like so:

```python
scheduler.schedule_skill(
    job_id="monad-daily",
    skill="testnet_daily_tx",
    args={
        "chain_slug": "monad_testnet",
        "wallet_label": "burner-evm-1",
        "jitter_seconds": 600,
    },
    cron="0 9 * * *",       # 09:00 UTC daily
)
```

Cron syntax is standard 5-field. Use `run_at_iso="..."` for one-shot jobs.
The scheduler starts inside the Telegram application's `post_init` hook,
which is where the asyncio event loop is live.

---

## Telegram commands

| Command | Effect |
|---------|--------|
| `/start` | Bot banner. |
| `/help` | Lists every skill currently exposed to the LLM. |
| `/status` | Disabled families, policy caps, last five audit rows. |
| `/disable <family>` | Remove a family (`wallet`, `x`, `testnet`, ...) from the tool list. |
| `/enable <family>` | Undo `/disable`. |
| `/reset` | Clear working memory for this chat. |

Non-command text is passed to the LLM.

---

## Development

### Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### First-time Telethon login (optional)

Only needed if you want `telegram_ops` skills (the userbot that joins
groups). Do this once on the VPS, not inside a containerised cron:

```bash
hermes-telethon-login            # installed by pyproject
# or:
python -m agent.tools.telethon_login
```

It prompts for phone / SMS code / 2FA password and writes
`data/userbot.session`.

### Tests

```bash
pytest -q
```

The suite stubs `CONFIG_DIR` / `DATA_DIR` into `tmp_path` per test, so it
never touches your real wallets or chain config. Covers the two
highest-blast-radius modules: `policy.py` and `wallets/store.py`.

### Lint / format

```bash
ruff check .
ruff format .
```

---

## Extending

Add a file under `src/agent/skills/<family>/<skill_name>.py`:

```python
from pydantic import BaseModel, Field
from agent.skills.base import Skill, SkillContext, SkillError


class FooInput(BaseModel):
    target: str = Field(..., description="Address or label.")


class FooOutput(BaseModel):
    message: str


class FooSkill(Skill):
    name = "research_foo"          # must match ^[a-zA-Z0-9_-]{1,64}$
    family = "research"            # used by /disable
    description = "One-line hint for the LLM."
    Input = FooInput
    Output = FooOutput

    async def run(self, inputs: FooInput, ctx: SkillContext) -> FooOutput:
        return FooOutput(message=f"hello, {inputs.target}")

    def summary(self, output: FooOutput) -> str:
        return output.message
```

The registry auto-discovers concrete `Skill` subclasses at boot. Set
`mutates_chain = True` if the skill broadcasts transactions, so the policy
layer can enforce simulate-first and mainnet confirmation.

---

## Operational notes

- **2 GB RAM is the floor.** The model runs remotely on OpenRouter, so
  only the Python process needs memory. Docker Compose caps the container
  at 1.4 GB to protect the rest of the VPS.
- **Disk growth.** The SQLite DB grows ~1 KB per tool call. Rotate or
  vacuum with `sqlite3 data/agent.db "VACUUM;"` if it matters.
- **Backups.** Snapshot `data/` (keystore + SQLite + scheduler jobs).
  Store `KEYSTORE_PASSWORD` in a password manager; without it the
  keystore is irrecoverable.
- **Upgrades.** `docker compose pull && docker compose up -d` after a
  `git pull`. The SQLite schema is backwards-compatible; adding a column
  requires a migration (see `memory/db.py`).

---

## Roadmap

Short-term (merge-ready scope):

- [x] Encrypted keystore + wallet lifecycle skills.
- [x] `wallet_send` with simulate-first.
- [x] `testnet_daily_tx`.
- [x] Notes (FTS5).
- [x] Self-preference updates.
- [x] Telethon login helper.
- [ ] `nft_mint_erc721` against a known collection.
- [ ] `token_deploy_erc20` with bundled bytecode.
- [ ] `x_follow` / `x_like` / `x_retweet` via Twikit.

Later:

- [ ] Cross-chain bridge skill (official bridges only).
- [ ] Inline-button confirmation for large tx (Telegram).
- [ ] Per-skill metrics in `/status`.

---

## License

MIT — see [LICENSE](LICENSE).

---

> This project automates actions on services whose Terms of Service
> typically forbid automation (X, Discord). Use it only on accounts and
> funds you are prepared to lose. The authors take no responsibility for
> account bans, lost funds, or contractual disputes arising from its use.
