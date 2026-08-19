"""Mubit poker system — session-stateful V11 configuration.

Reconstruction of the V11 "poker-session-full" system that produced +10.8%
gain (the original lived in a /tmp clone lost to a purge; the override is
small and fully specified in the session records).

Two mechanisms combine (this was the V11 breakthrough):
1. Implicit session memory — the model maintains conversation history ACROSS
   hands (the parent clears it at instance boundaries; we trim instead),
   calibrating play over the session like ICL.
2. Explicit opponent intelligence — Mubit lessons distilled per opponent
   (the parent's poker distiller + retrieval key, unchanged).

The trim cap keeps context bounded: MAX_SESSION_MESSAGES most recent turns
survive each hand boundary.
"""

from __future__ import annotations


from ...registry import register_system
from ..mubit_genai.system import MubitGenAISystem
from ...interface import Observation, Query, observation_marks_instance_complete


@register_system("mubit_poker")
class MubitPokerSystem(MubitGenAISystem):
    """Mubit + session-stateful conversation for exploitable poker."""

    MAX_SESSION_MESSAGES = 120

    def observe(
        self, observation: Observation, next_query: Query = None
    ) -> None:
        instance_complete = observation_marks_instance_complete(observation)
        content = observation.content.strip()

        self._last_turn_feedback = content or None

        # Capture episode + write lesson exactly as the parent does.
        if self._last_response is not None:
            _a = self._last_response.action
            _astr = _a.model_dump_json() if hasattr(_a, "model_dump_json") else str(_a)
            self._episode_steps.append((_astr, content))

        if instance_complete and self._last_query and self._last_response:
            self._write_lesson(self._last_query, self._last_response, content)

        if content:
            self._add_message("user", f"FEEDBACK: {content}")

        if instance_complete:
            # V11 core difference: do NOT clear the conversation at hand
            # boundaries — keep a rolling session window so play calibrates
            # across hands. Memory (Mubit lessons) still injects at the start
            # of each new hand via _at_instance_boundary.
            if len(self.messages) > self.MAX_SESSION_MESSAGES:
                self.messages = self.messages[-self.MAX_SESSION_MESSAGES:]
            self._last_turn_feedback = None
            self._at_instance_boundary = True
            self._episode_steps = []
            self._instance_first_prompt = None

    @property
    def name(self) -> str:
        return "mubit_poker"
