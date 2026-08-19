"""
Mubit full-stack continual learning system.

Extends the base ``mubit`` system (lesson storage + retrieval injection) with
Mubit's reinforcement and consolidation machinery:

1. **Outcome reinforcement.** Each turn, the ids of retrieved lessons are
   recorded. When the instance completes, the outcome is fed back to Mubit via
   ``record_outcome()`` against every lesson that was retrieved for the
   winning/losing instance. This exercises Mubit's per-entry
   success/failure/partial counters + Bayesian confidence update, so lessons
   that repeatedly help get up-weighted and lessons that hurt get down-weighted
   in future retrieval.

2. **Periodic reflection.** Every ``reflect_every`` completed instances, invoke
   ``reflect()`` to let Mubit consolidate accumulated evidence into derived
   lessons. This runs best-effort (the instance may have no control LLM
   configured, in which case reflect degrades to a heuristic no-op).

Memory semantics, run scoping, and baseline isolation are inherited unchanged
from ``MubitMemorySystem``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...interface import (
    Observation,
    Query,
    Response,
    observation_marks_instance_complete,
)
from ...registry import register_system
from ..mubit.system import (
    DEFAULT_MODEL,
    DEFAULT_TOP_K,
    MubitMemorySystem,
)

logger = logging.getLogger(__name__)

# Outcome string the benchmark signals map to Mubit outcome values.
_OUTCOME_MAP = {"won": "success", "lost": "failure", "tied": "neutral", "neutral": "neutral"}


@register_system("mubit_full")
class MubitFullSystem(MubitMemorySystem):
    """Mubit memory + outcome reinforcement + periodic reflection."""

    supports_baseline = True
    parallel_safe = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        share_scope: str = "run",
        reflect_every: int = 5,
        reinforce_retrieved: bool = True,
    ):
        super().__init__(
            model=model,
            top_k=top_k,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            share_scope=share_scope,
        )
        self.reflect_every = max(int(reflect_every), 0)
        self.reinforce_retrieved = bool(reinforce_retrieved)
        # Instance ids whose retrieved lessons we are still tracking for
        # reinforcement, plus the retrieved entry ids per instance.
        self._pending_retrieved_ids: dict[str, list[str]] = {}
        self._completed_instances: int = 0

    # ---- overrides ----

    def respond(self, query: Query) -> Response:
        response = super().respond(query)
        if self.reinforce_retrieved:
            # Capture the entry ids of lessons retrieved for this instance so
            # we can reinforce them once the instance resolves. Stored in the
            # response metadata by the base class.
            ids = []
            for m in (response.metadata or {}).get("retrieved_lessons_meta") or []:
                eid = m.get("id")
                if eid:
                    ids.append(str(eid))
            if ids and query.instance_id:
                self._pending_retrieved_ids[query.instance_id] = ids
        return response

    def observe(
        self, observation: Observation, next_query: Optional[Query] = None
    ) -> None:
        instance_complete = observation_marks_instance_complete(observation)
        content = observation.content.strip()

        # Let the base class store the lesson + update conversation state, but
        # capture the (query, outcome) for reinforcement first, since the base
        # clears _last_query/_last_response.
        if instance_complete and self._last_query and self.reinforce_retrieved:
            self._reinforce_for_outcome(self._last_query.instance_id, content)

        super().observe(observation, next_query=next_query)

        if instance_complete:
            self._completed_instances += 1
            if self.reflect_every and self._completed_instances % self.reflect_every == 0:
                self._maybe_reflect()

    def reset(self) -> None:
        super().reset()
        self._pending_retrieved_ids = {}
        self._completed_instances = 0

    @property
    def name(self) -> str:
        return "mubit_full"

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:
        base = super().get_run_artifacts() or {}
        base.update(
            {
                "artifact_type": "mubit_full",
                "reflect_every": self.reflect_every,
                "reinforce_retrieved": self.reinforce_retrieved,
                "completed_instances": self._completed_instances,
            }
        )
        return base

    # ---- internal ----

    def _reinforce_for_outcome(self, instance_id: Optional[str], feedback: str) -> None:
        if self._client is None or instance_id is None:
            return
        outcome_label = "neutral"
        c = feedback.upper()
        if "WON" in c:
            outcome_label = "won"
        elif "LOST" in c:
            outcome_label = "lost"
        elif "TIED" in c:
            outcome_label = "tied"
        mubit_outcome = _OUTCOME_MAP.get(outcome_label, "neutral")
        # Positive signal for wins, negative for losses, neutral otherwise.
        signal = {"won": 1.0, "lost": -1.0}.get(outcome_label, 0.0)
        ids = self._pending_retrieved_ids.pop(instance_id, [])
        for eid in ids:
            try:
                self._client.record_outcome(
                    reference_id=eid,
                    outcome=mubit_outcome,
                    signal=signal,
                    rationale=f"instance {instance_id} outcome={outcome_label}",
                    agent_id="clbench-mubit-full",
                )
            except Exception:
                logger.debug("record_outcome failed for %s", eid, exc_info=True)
        # If the instance had no retrieved lessons but completed, nothing to do.

    def _maybe_reflect(self) -> None:
        if self._client is None:
            return
        try:
            self._client.reflect(last_n_items=20)
        except Exception:
            logger.debug("reflect failed", exc_info=True)
