"""APScheduler with SQLite jobstore - persistent cron/one-shot jobs.

Wraps APScheduler's AsyncIOScheduler so jobs survive restarts, and exposes
a tiny helper to run a named skill on a schedule.

Cron example (every day at 09:00 UTC)::

    scheduler.schedule_skill(
        job_id="monad-daily",
        skill="testnet.daily_tx",
        args={"chain_slug": "monad_testnet", "wallet_label": "burner-evm-1"},
        cron="0 9 * * *",
    )
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .config import get_settings
from .skills import SkillContext, SkillRegistry

log = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self, registry: SkillRegistry, deps: Any) -> None:
        db_url = f"sqlite:///{get_settings().data_dir / 'scheduler.db'}"
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)},
            timezone="UTC",
        )
        self._registry = registry
        self._deps = deps

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def schedule_skill(
        self,
        *,
        job_id: str,
        skill: str,
        args: dict[str, Any],
        cron: str | None = None,
        run_at_iso: str | None = None,
        replace: bool = True,
    ) -> None:
        if cron is None and run_at_iso is None:
            raise ValueError("must provide cron or run_at_iso")
        if cron and run_at_iso:
            raise ValueError("pick one: cron OR run_at_iso")

        trigger = (
            CronTrigger.from_crontab(cron) if cron
            else DateTrigger(run_date=run_at_iso)
        )
        self._scheduler.add_job(
            _run_skill_wrapper,
            trigger=trigger,
            id=job_id,
            replace_existing=replace,
            kwargs={
                "skill_name": skill,
                "args": args,
                # Function refs in APScheduler's SQLAlchemy jobstore must be
                # importable by path; we pass only primitives here and re-
                # resolve the registry at run time via a module-level getter.
            },
        )

    def remove(self, job_id: str) -> bool:
        try:
            self._scheduler.remove_job(job_id)
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_jobs(self) -> list[dict[str, str]]:
        return [
            {"id": j.id, "next_run_time": str(j.next_run_time), "trigger": str(j.trigger)}
            for j in self._scheduler.get_jobs()
        ]


# --- Module-level skill runner (must be importable by APScheduler) -----
_ACTIVE: dict[str, Any] = {}


def register_runtime(registry: SkillRegistry, deps: Any) -> None:
    """Called once at startup so the jobstore can resolve skills by name."""
    _ACTIVE["registry"] = registry
    _ACTIVE["deps"] = deps


async def _run_skill_wrapper(skill_name: str, args: dict[str, Any]) -> None:
    if "registry" not in _ACTIVE:
        log.error("scheduled skill %s fired before register_runtime()", skill_name)
        return
    registry: SkillRegistry = _ACTIVE["registry"]
    deps = _ACTIVE["deps"]
    ctx = SkillContext(
        chat_id=None,
        extras={
            "evm_pool": getattr(deps, "evm_pool", None),
            "solana_pool": getattr(deps, "solana_pool", None),
            "scheduler": getattr(deps, "scheduler", None),
        },
    )
    try:
        _, out = await registry.dispatch(skill_name, args, ctx)
        log.info("scheduled %s -> %s", skill_name, out.model_dump())
    except Exception:  # noqa: BLE001
        log.exception("scheduled skill %s failed", skill_name)
