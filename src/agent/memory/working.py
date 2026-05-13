"""In-process ring buffer of recent chat turns, keyed by chat_id.

Not persisted - cheap to lose, cheap to rebuild. The expensive-to-lose stuff
(tool calls, notes, tasks) lives in SQLite.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock


@dataclass
class Turn:
    role: str   # "user" | "assistant" | "tool" | "system"
    content: str
    # Hermes tool-call metadata, optional
    tool_call_id: str | None = None
    tool_name: str | None = None


class WorkingMemory:
    def __init__(self, maxlen_per_chat: int = 24) -> None:
        self._chats: dict[int, deque[Turn]] = {}
        self._max = maxlen_per_chat
        self._lock = RLock()

    def append(self, chat_id: int, turn: Turn) -> None:
        with self._lock:
            buf = self._chats.setdefault(chat_id, deque(maxlen=self._max))
            buf.append(turn)

    def history(self, chat_id: int) -> list[Turn]:
        with self._lock:
            return list(self._chats.get(chat_id, ()))

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._chats.pop(chat_id, None)
