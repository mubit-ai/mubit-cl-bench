"""Mubit GPT-5.4-tuned system — minimal-injection variant.

Forensic finding: GPT-5.4's stateless baselines are already high; injecting
general knowledge it already has adds noise. This variant:
1. Injects FEWER lessons (top_k=2, not 6)
2. Only injects at instance START (never per-turn)
3. Uses error-driven quickstart for codebase: only previous ERROR→SOLUTION
   pairs (the one thing the model can't know), never basic commands
4. No session-statefulness for poker — resets each hand, lessons only
"""

from __future__ import annotations

from ...interface import Query, Response
from ...registry import register_system
from ..mubit.system import MubitMemorySystem, _detect_task


@register_system("mubit_tuned")
class MubitTunedSystem(MubitMemorySystem):
    """Minimal-injection variant tuned for strong models (GPT-5.4+)."""

    def __init__(
        self,
        model: str = "gpt-5.4",
        top_k: int = 2,
        system_prompt: str = "",
        max_tokens=None,
        share_scope: str = "run",
    ):
        # top_k defaults to 2 (from 6) — less noise for strong models
        super().__init__(
            model=model,
            top_k=top_k,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            share_scope=share_scope,
        )

    def _codebase_quickstart(self, query: Query) -> str:
        """GPT-5.4 variant: only ERROR→SOLUTION pairs, never basic commands."""
        if self._client is None:
            return ""
        import re as _re

        _anchor = self._instance_first_prompt or query.prompt
        m = _re.search(
            r"(?:repo|repository)[:\s]+([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)",
            query.prompt + " " + _anchor, _re.IGNORECASE,
        )
        cur_repo = m.group(1) if m else None

        if not cur_repo:
            return ""

        lines: list[str] = []
        try:
            out = self._client.recall(
                query=f"codebase {cur_repo} SOLVED error fix",
                limit=self.top_k,
                entry_types=["lesson"],
                include_working_memory=False,
            )
            for e in out.get("evidence") or []:
                text = e.get("text") or e.get("content") or ""
                meta = e.get("metadata") or {}
                # Only same-repo, SOLVED lessons
                lrepo = meta.get("repo")
                if not lrepo:
                    m2 = _re.match(r"\[([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)\]", text)
                    lrepo = m2.group(1) if m2 else None
                if lrepo and lrepo != cur_repo:
                    continue
                if "SOLVED" not in text:
                    continue
                # Extract only the error→fix pair (skip commands the model knows)
                err_m = _re.search(r"errors?:\s*([^.]+)", text)
                fix_m = _re.search(r"files?:\s*([^\s]+(?:,\s*[^\s]+)*)", text)
                if err_m and fix_m:
                    lines.append(f"  {err_m.group(1).strip()[:80]} → fixed in {fix_m.group(1)}")
        except Exception:
            pass

        if not lines:
            return ""
        return "\n".join(lines[:2])  # max 2 error→solution pairs

    @property
    def name(self) -> str:
        return "mubit_tuned"
