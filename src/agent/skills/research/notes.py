"""Note-taking skills backed by SQLite FTS5.

Two skills:

* ``notes_add``   -> persist a free-form note with an optional tag.
* ``notes_search`` -> full-text search over all notes, returns ranked matches.

The ``notes_fts`` virtual table + triggers are already defined in
``memory/db.py``, so every insert/update/delete on ``notes`` is indexed
automatically.

FTS5 MATCH query syntax is permissive: bare words, ``AND``/``OR``/``NOT``,
``"quoted phrase"``, prefix with ``*``. We pass the user's query through
``_sanitize_fts_query`` to strip control characters that would otherwise
raise ``sqlite3.OperationalError``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ...memory import get_db
from ..base import Skill, SkillContext, SkillError


# ---------- notes_add -----------------------------------------------------


class NotesAddInput(BaseModel):
    body: str = Field(..., min_length=1, description="Note contents. Any length.")
    tag: str | None = Field(
        default=None,
        description="Optional short tag, e.g. 'airdrop', 'monad', 'reminder'.",
        max_length=64,
    )


class NotesAddOutput(BaseModel):
    id: int
    ts: str
    tag: str | None
    preview: str


class NotesAddSkill(Skill):
    name = "notes_add"
    family = "research"
    description = (
        "Persist a free-form note. Supports an optional short tag. "
        "Notes are full-text searchable via notes_search."
    )
    Input = NotesAddInput
    Output = NotesAddOutput
    touches_filesystem = True

    async def run(self, inputs: NotesAddInput, ctx: SkillContext) -> NotesAddOutput:
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO notes (tag, body) VALUES (?, ?)",
                (inputs.tag, inputs.body),
            )
            note_id = int(cur.lastrowid or 0)
            row = conn.execute(
                "SELECT id, ts, tag, body FROM notes WHERE id=?", (note_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise SkillError("failed to persist note")
        preview = (row["body"] or "")[:120]
        return NotesAddOutput(id=row["id"], ts=row["ts"], tag=row["tag"], preview=preview)

    def summary(self, output: NotesAddOutput) -> str:
        tag = f"[{output.tag}] " if output.tag else ""
        return f"note #{output.id} saved: {tag}{output.preview}"


# ---------- notes_search --------------------------------------------------


class NotesSearchInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "FTS5 query. Plain words work; also supports AND/OR/NOT and "
            '"quoted phrase". Prefix matching with trailing *.'
        ),
    )
    tag: str | None = Field(
        default=None, description="Optional tag filter (exact match)."
    )
    limit: int = Field(default=10, ge=1, le=50)


class NoteHit(BaseModel):
    id: int
    ts: str
    tag: str | None
    body: str
    rank: float


class NotesSearchOutput(BaseModel):
    query: str
    hits: list[NoteHit]


class NotesSearchSkill(Skill):
    name = "notes_search"
    family = "research"
    description = (
        "Full-text search over stored notes (FTS5 MATCH). Returns ranked hits "
        "with timestamp and tag. Read-only."
    )
    Input = NotesSearchInput
    Output = NotesSearchOutput

    async def run(self, inputs: NotesSearchInput, ctx: SkillContext) -> NotesSearchOutput:
        fts_q = _sanitize_fts_query(inputs.query)
        if not fts_q:
            return NotesSearchOutput(query=inputs.query, hits=[])

        # FTS5 returns a negative 'rank' where smaller is better; we flip sign
        # for human-friendly "higher = more relevant".
        sql = """
            SELECT n.id, n.ts, n.tag, n.body, notes_fts.rank AS rank
              FROM notes_fts
              JOIN notes n ON n.id = notes_fts.rowid
             WHERE notes_fts MATCH ?
        """
        params: list = [fts_q]
        if inputs.tag:
            sql += " AND n.tag = ?"
            params.append(inputs.tag)
        sql += " ORDER BY notes_fts.rank LIMIT ?"
        params.append(inputs.limit)

        conn = get_db()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        hits = [
            NoteHit(
                id=r["id"], ts=r["ts"], tag=r["tag"], body=r["body"],
                rank=float(-r["rank"]) if r["rank"] is not None else 0.0,
            )
            for r in rows
        ]
        return NotesSearchOutput(query=inputs.query, hits=hits)

    def summary(self, output: NotesSearchOutput) -> str:
        if not output.hits:
            return f"no notes matched {output.query!r}"
        heads = [f"#{h.id}({h.tag or '-'}): {h.body[:60]}" for h in output.hits[:3]]
        more = "" if len(output.hits) <= 3 else f" (+{len(output.hits) - 3} more)"
        return "; ".join(heads) + more


# ---------- helpers -------------------------------------------------------

# Strip FTS5 control chars that would raise OperationalError on malformed query.
# Keep operators the user might actually intend: AND OR NOT () " * :
_FTS_SAFE_RE = re.compile(r'[^A-Za-z0-9_\s\-\(\)\"\*\:]')


def _sanitize_fts_query(q: str) -> str:
    cleaned = _FTS_SAFE_RE.sub(" ", q).strip()
    return re.sub(r"\s+", " ", cleaned)
