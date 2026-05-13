"""Entry point - wires everything together.

Boot order:
  1. logging + settings sanity check
  2. init SQLite schema
  3. build web3 client pools (lazy - no RPC hit at boot)
  4. load skill registry (auto-discovers all submodules)
  5. build HermesAgent
  6. build Telegram Application
  7. attach scheduler.start() to Application.post_init (runs inside PTB's
     asyncio loop, which is what APScheduler's AsyncIOScheduler requires)
  8. run_polling (blocks)
"""

from __future__ import annotations

import logging
import sys

import structlog
from telegram.ext import Application

from .config import get_settings
from .interfaces.telegram_bot import build_application, make_audit_sink
from .llm import AgentDeps, HermesAgent
from .memory import WorkingMemory, init_db
from .scheduler import AgentScheduler, register_runtime
from .skills import SkillRegistry
from .web3_clients import EvmClientPool, SolanaClientPool


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    for noisy in ("httpx", "httpcore", "telegram.ext", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )


def _preflight() -> None:
    s = get_settings()
    missing = []
    if not s.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    if not s.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not s.telegram_owner_id:
        missing.append("TELEGRAM_OWNER_ID")
    if not s.keystore_password:
        missing.append("KEYSTORE_PASSWORD")
    if missing:
        raise SystemExit(f"missing required env vars: {missing}")


def main() -> None:
    _configure_logging()
    log = logging.getLogger("agent.main")
    _preflight()
    init_db()

    evm_pool = EvmClientPool()
    sol_pool = SolanaClientPool()

    registry = SkillRegistry()
    registry.discover()
    log.info("registered %d skills", len(registry.all()))

    deps = AgentDeps(evm_pool=evm_pool, solana_pool=sol_pool)
    scheduler = AgentScheduler(registry, deps)
    deps.scheduler = scheduler
    register_runtime(registry, deps)

    working = WorkingMemory()
    agent = HermesAgent(registry=registry, working=working, deps=deps)

    app = build_application(agent, working)
    audit = make_audit_sink(app)
    if audit is not None:
        deps.audit_sink = audit

    # AsyncIOScheduler must attach to a running event loop. PTB's post_init
    # hook runs after the asyncio loop is up but before polling starts.
    async def _post_init(_app: Application) -> None:
        scheduler.start()
        log.info("scheduler started with %d persisted jobs",
                 len(scheduler.list_jobs()))

    async def _post_shutdown(_app: Application) -> None:
        scheduler.shutdown()

    app.post_init = _post_init
    app.post_shutdown = _post_shutdown

    log.info("hermes-agent ready; polling Telegram")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
