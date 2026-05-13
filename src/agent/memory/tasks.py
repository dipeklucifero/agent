"""Persistent task queue.

APScheduler itself also uses a SQLite jobstore (see ``scheduler.py``) for
time-based scheduling. This table is for human-visible bookkeeping:
"what am I meant to be doing?" vs APScheduler's "when do I run it?".
Both can coexist - tasks here can reference an APScheduler job id in
`schedule` as an ISO datetime or cron expression.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .db import get_db

Status = Literal["pending", "running", "done", "failed", "cancelled"]


@dataclass
class Task:
    id: int
    created_ts: str
    title: str
    description: str | None
    schedule: str | None
    status: Status
    last_run_ts: str | None
    last_result: str | None
    run_count: int


class TaskQueue:
    def add(
        self,
        *,
        title: str,
        description: str | None = None,
        schedule: str | None = None,
    ) -> int:
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO tasks (title, description, schedule) VALUES (?,?,?)",
                (title, description, schedule),
            )
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def list(self, status: Status | None = None) -> list[Task]:
        conn = get_db()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY id DESC"
                ).fetchall()
            return [Task(**dict(r)) for r in rows]
        finally:
            conn.close()

    def mark(
        self,
        task_id: int,
        status: Status,
        last_result: str | None = None,
    ) -> None:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE tasks SET status=?, last_result=?, "
                "last_run_ts=datetime('now'), run_count=run_count+1 WHERE id=?",
                (status, last_result, task_id),
            )
        finally:
            conn.close()
