"""Auto-discovering skill registry.

Walks ``agent.skills`` at import time, finds every concrete ``Skill``
subclass, and indexes it by ``name``. Also provides:

* ``tool_specs()`` - the JSON-schema array passed to Hermes.
* ``dispatch(name, raw, ctx)`` - validate + run a tool call.
* ``families()`` - for the ``disabled_skill_families`` kill switch.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from .base import Skill, SkillContext, SkillError


class SkillRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, Skill] = {}

    # ----- discovery -----------------------------------------------------
    def discover(self, package: str = "agent.skills") -> None:
        """Import every submodule under `package` so subclasses register."""
        pkg = importlib.import_module(package)
        prefix = pkg.__name__ + "."
        for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix):
            # Skip internal modules: base, registry.
            tail = modname.rsplit(".", 1)[-1]
            if tail in {"base", "registry"}:
                continue
            importlib.import_module(modname)

        for cls in _iter_concrete_subclasses(Skill):
            if not cls.name:
                continue
            instance = cls()
            self._by_name[cls.name] = instance

    # ----- querying ------------------------------------------------------
    def all(self) -> list[Skill]:
        return list(self._by_name.values())

    def get(self, name: str) -> Skill | None:
        return self._by_name.get(name)

    def families(self) -> set[str]:
        return {s.family for s in self._by_name.values() if s.family}

    def tool_specs(self, disabled_families: list[str] | None = None) -> list[dict[str, Any]]:
        disabled = set(disabled_families or [])
        return [
            type(s).tool_spec()
            for s in self._by_name.values()
            if s.family not in disabled
        ]

    # ----- dispatch ------------------------------------------------------
    async def dispatch(
        self, name: str, raw_args: dict[str, Any], ctx: SkillContext
    ) -> tuple[Skill, Any]:
        skill = self._by_name.get(name)
        if skill is None:
            raise SkillError(f"unknown skill: {name}")
        output = await skill.invoke(raw_args, ctx)
        return skill, output


def _iter_concrete_subclasses(root: type) -> list[type]:
    out: list[type] = []
    stack = [root]
    seen: set[type] = set()
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            stack.append(sub)
            # Concrete if no abstract methods left.
            if not getattr(sub, "__abstractmethods__", None):
                out.append(sub)
    return out
