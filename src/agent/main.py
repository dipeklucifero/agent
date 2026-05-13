"""Entry point - wires everything together.

Boot order:
  1. logging + settings sanity check
  2. init SQLite schema
  3. build web3 client pools (lazy - no RPC hit at boot)
  4. load skill registry (auto-discovers all submodules)
  5. start APScheduler
  6. build HermesAgent with its deps
  7. build Telegram Application, attach audit sink
  8. run_polling (blocks)
"""

from __future__ import annotations

import logging
import sys

import structlog

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
    # Tame the noisiest libs.
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
    scheduler.start()

    working = WorkingMemory()
    agent = HermesAgent(registry=registry, working=working, deps=deps)

    app = build_application(agent, working)
    audit = make_audit_sink(app)
    if audit is not None:
        deps.audit_sink = audit

    log.info("hermes-agent ready; polling Telegram")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
