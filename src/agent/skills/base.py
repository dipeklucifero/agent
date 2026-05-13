"""Skill ABC + shared types.

A Skill is a single unit of agent capability: takes typed inputs, returns
typed output, logs an episode, and returns a short ``summary`` string
suitable for the LLM to feed back into its next turn.

Subclasses declare:
  * ``name``   - stable identifier, snake_case, e.g. ``wallet.balance``.
  * ``family`` - kill-switch group, e.g. ``wallet``, ``x``, ``system``.
  * ``Input``  - Pydantic model describing arguments.
  * ``Output`` - Pydantic model describing results.
  * ``summary(output)`` - one-line human-readable result.
  * ``run(inputs, ctx)`` - the actual implementation (async allowed).

The registry introspects these class attrs to produce the JSON Schema
Hermes needs for tool-calling, and to dispatch calls at runtime.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

I = TypeVar("I", bound=BaseModel)
O = TypeVar("O", bound=BaseModel)


@dataclass
class SkillContext:
    """Anything a skill might need that shouldn't be in its inputs."""
    chat_id: int | None = None
    # Populated by the agent loop before calling. Skills import these lazily
    # to avoid a circular import.
    extras: dict[str, Any] | None = None


class SkillError(Exception):
    """Raised by a skill when inputs are invalid or execution fails in a
    way the LLM should learn from (will be returned as tool-role content)."""


class SkillDenied(SkillError):
    """Raised by the policy layer when a call is blocked. Distinguished
    from SkillError so the audit log can record ``status='denied'``."""


class Skill(ABC, Generic[I, O]):
    # Override in subclasses:
    name: ClassVar[str] = ""
    family: ClassVar[str] = ""
    description: ClassVar[str] = ""
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]

    # Metadata that the policy layer reads.
    # ``mutates_chain`` => may broadcast a tx; always require simulate-first.
    mutates_chain: ClassVar[bool] = False
    # ``touches_filesystem`` => may write under config/ or data/.
    touches_filesystem: ClassVar[bool] = False
    # ``social`` => subject to social_pacing policy.
    social: ClassVar[bool] = False

    @abstractmethod
    async def run(self, inputs: I, ctx: SkillContext) -> O:  # pragma: no cover
        ...

    def summary(self, output: O) -> str:
        """Human-readable one-liner for the LLM. Override for richer output."""
        return output.model_dump_json()

    # ----- call wrapper --------------------------------------------------
    async def invoke(self, raw: dict[str, Any], ctx: SkillContext) -> O:
        """Validate, coerce, then run."""
        try:
            inputs = self.Input.model_validate(raw)  # type: ignore[assignment]
        except Exception as e:
            raise SkillError(f"invalid inputs for {self.name}: {e}") from e
        result = self.run(inputs, ctx)  # type: ignore[arg-type]
        if inspect.isawaitable(result):
            result = await result
        return result  # type: ignore[return-value]

    # ----- introspection -------------------------------------------------
    @classmethod
    def tool_spec(cls) -> dict[str, Any]:
        """OpenAI-compatible tool schema. Hermes via OpenRouter uses this
        shape for its tool-calling JSON."""
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description.strip(),
                "parameters": cls.Input.model_json_schema(),
            },
        }
