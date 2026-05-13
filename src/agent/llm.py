"""Hermes tool-calling loop via OpenRouter.

OpenRouter speaks the OpenAI Chat Completions API, so we use the official
``openai`` SDK pointed at ``https://openrouter.ai/api/v1``. Nous Research's
Hermes 3/4 models are tool-use fine-tuned and follow the standard
``tools=[...]`` / ``tool_calls`` contract.

The loop:

    user -> system+history+user -> model
    while model returned tool_calls:
        for each tool_call:
            policy.check()            # deny or mutate args
            registry.dispatch()       # run the skill
            append tool-role msg with the JSON result
        model <- updated transcript
    return final assistant text

There's a hard cap on iterations to prevent infinite tool-call storms.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .config import get_settings
from .memory import EpisodicMemory, WorkingMemory
from .memory.working import Turn
from .policy import PolicyEngine
from .skills import SkillContext, SkillDenied, SkillError, SkillRegistry
from .soul import build_system_prompt

log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 8
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


@dataclass
class AgentDeps:
    """Shared handles passed into every skill invocation via SkillContext.extras."""
    evm_pool: Any = None
    solana_pool: Any = None
    scheduler: Any = None
    audit_sink: Any = None  # optional async callable(msg: str) -> None


class HermesAgent:
    def __init__(
        self,
        registry: SkillRegistry,
        working: WorkingMemory,
        deps: AgentDeps,
    ) -> None:
        s = get_settings()
        self._client = AsyncOpenAI(
            base_url=_OPENROUTER_BASE,
            api_key=s.openrouter_api_key,
            default_headers={
                # Optional but nice - OpenRouter uses these for analytics.
                "X-Title": "hermes-agent",
            },
        )
        self._model = s.hermes_model
        self._fallback_model = s.hermes_fallback_model
        self._registry = registry
        self._working = working
        self._policy = PolicyEngine()
        self._episodic = EpisodicMemory()
        self._deps = deps

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    # -----------------------------------------------------------------
    async def handle(self, *, chat_id: int, user_text: str) -> str:
        self._working.append(chat_id, Turn(role="user", content=user_text))
        messages = self._build_messages(chat_id)
        tools = self._registry.tool_specs(
            disabled_families=list(_disabled_families())
        )

        ctx = SkillContext(
            chat_id=chat_id,
            extras={
                "evm_pool": self._deps.evm_pool,
                "solana_pool": self._deps.solana_pool,
                "scheduler": self._deps.scheduler,
            },
        )

        for _iter in range(_MAX_TOOL_ITERATIONS):
            resp = await self._complete(messages=messages, tools=tools)
            msg = resp.choices[0].message
            messages.append(_assistant_msg_to_dict(msg))

            if not msg.tool_calls:
                final = (msg.content or "").strip()
                self._working.append(chat_id, Turn(role="assistant", content=final))
                return final or "(no reply)"

            for call in msg.tool_calls:
                tool_result = await self._run_tool(call, ctx, user_text)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": tool_result,
                    }
                )

        # Too many iterations - break the loop.
        return "I got stuck looping tool calls. Please rephrase or simplify."

    # -----------------------------------------------------------------
    async def _complete(self, *, messages: list[dict], tools: list[dict]):
        """Call primary model, fall back to the smaller Hermes on error."""
        try:
            return await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.3,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("primary model %s failed (%s); falling back", self._model, e)
            return await self._client.chat.completions.create(
                model=self._fallback_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.3,
            )

    # -----------------------------------------------------------------
    async def _run_tool(self, call, ctx: SkillContext, user_turn_text: str) -> str:
        name = call.function.name
        try:
            raw = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError as e:
            return _tool_error(name, f"invalid JSON args: {e}")

        skill = self._registry.get(name)
        if skill is None:
            return _tool_error(name, f"unknown skill: {name}")

        decision = self._policy.check(
            skill=skill, args=raw, user_turn_text=user_turn_text
        )
        if not decision.allowed:
            self._episodic.log(
                chat_id=ctx.chat_id, skill=name, inputs=raw,
                result={"denied": decision.reason}, status="denied",
                notes=decision.reason,
            )
            return _tool_error(name, f"DENIED: {decision.reason}")

        args = decision.args or raw
        try:
            _, output = await self._registry.dispatch(name, args, ctx)
        except SkillDenied as e:
            self._episodic.log(
                chat_id=ctx.chat_id, skill=name, inputs=args,
                result={"denied": str(e)}, status="denied", notes=str(e),
            )
            return _tool_error(name, f"DENIED: {e}")
        except SkillError as e:
            self._episodic.log(
                chat_id=ctx.chat_id, skill=name, inputs=args,
                result={"error": str(e)}, status="error", notes=str(e),
            )
            return _tool_error(name, f"ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("skill %s crashed", name)
            self._episodic.log(
                chat_id=ctx.chat_id, skill=name, inputs=args,
                result={"error": repr(e)}, status="error", notes=repr(e),
            )
            return _tool_error(name, f"INTERNAL ERROR: {e!r}")

        status = "simulated" if args.get("simulate") else "ok"
        self._episodic.log(
            chat_id=ctx.chat_id, skill=name, inputs=args,
            result=output.model_dump(), status=status,
            notes=skill.summary(output),
        )
        if self._deps.audit_sink is not None:
            try:
                await self._deps.audit_sink(
                    f"[{status}] {name}: {skill.summary(output)}"
                )
            except Exception:  # noqa: BLE001
                log.debug("audit_sink failed", exc_info=True)
        return json.dumps(output.model_dump(), default=str)

    # -----------------------------------------------------------------
    def _build_messages(self, chat_id: int) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": build_system_prompt()}]
        for t in self._working.history(chat_id):
            if t.role in ("user", "assistant"):
                msgs.append({"role": t.role, "content": t.content})
        return msgs


def _disabled_families() -> set[str]:
    from .config import load_policies
    return set(load_policies().disabled_skill_families)


def _assistant_msg_to_dict(msg) -> dict:
    """Convert openai SDK ChatCompletionMessage to a dict suitable for replay.

    When the assistant calls tools, Hermes/OpenAI expect content=None (not ""),
    otherwise some providers return a 400 on the next round-trip.
    """
    out: dict[str, Any] = {"role": "assistant"}
    if msg.tool_calls:
        out["content"] = msg.content  # may be None
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            }
            for c in msg.tool_calls
        ]
    else:
        out["content"] = msg.content or ""
    return out


def _tool_error(name: str, msg: str) -> str:
    return json.dumps({"tool": name, "error": msg})
