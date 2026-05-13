"""Append-only audit log of every skill invocation.

Also exposes a per-day counter helper used by policy (e.g., cap on how many
wallets the agent may create autonomously in one day).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Literal

from .db import get_db

Status = Literal["ok", "error", "simulated", "denied"]


@dataclass
class EpisodeRow:
    id: int
    ts: str
    chat_id: int | None
    skill: str
    input_json: str
    result_json: str | None
    status: Status
    tx_hash: str | None
    chain: str | None
    notes: str | None


class EpisodicMemory:
    def log(
        self,
        *,
        chat_id: int | None,
        skill: str,
        inputs: dict[str, Any],
        result: Any,
        status: Status,
        tx_hash: str | None = None,
        chain: str | None = None,
        notes: str | None = None,
    ) -> int:
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO episodic
                     (chat_id, skill, input_json, result_json, status, tx_hash, chain, notes)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    chat_id,
                    skill,
                    json.dumps(inputs, default=str),
                    json.dumps(result, default=str) if result is not None else None,
                    status,
                    tx_hash,
                    chain,
                    notes,
                ),
            )
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def recent(self, limit: int = 20) -> list[EpisodeRow]:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM episodic ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [EpisodeRow(**dict(r)) for r in rows]
        finally:
            conn.close()

    # ----- daily counters ------------------------------------------------
    @staticmethod
    def _today() -> str:
        return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")

    def bump_counter(self, key: str) -> int:
        """Atomically increment today's counter for `key`, return new value."""
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            day = self._today()
            conn.execute(
                "INSERT INTO counters(key, day, n) VALUES (?,?,1) "
                "ON CONFLICT(key, day) DO UPDATE SET n = n + 1",
                (key, day),
            )
            row = conn.execute(
                "SELECT n FROM counters WHERE key=? AND day=?", (key, day)
            ).fetchone()
            conn.execute("COMMIT")
            return int(row["n"]) if row else 1
        finally:
            conn.close()

    def counter(self, key: str) -> int:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT n FROM counters WHERE key=? AND day=?", (key, self._today())
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()
