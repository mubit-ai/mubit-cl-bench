"""
Mubit memory-backed continual learning system.

Uses a running Mubit instance (typed cognitive memory store) for cross-instance
learning. After each task instance completes, the system writes a distilled
**lesson** summarising what was observed and its outcome; before producing each
action it retrieves the most relevant prior lessons and injects them into the
prompt as an opponent/environment model.

This mirrors the mem0 system shape (retrieval-injected-into-prompt) but swaps
mem0's qdrant+LLM-extraction for Mubit's typed-memory + semantic recall, and
mirrors icl_notepad's instance-boundary clearing discipline.

Configuration:
  MUBIT_API_KEY   API key for the Mubit instance (required).
  MUBIT_ENDPOINT  HTTP endpoint (default http://127.0.0.1:3320).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Optional

from pydantic import BaseModel

from ...interface import (
    ContinualLearningSystem,
    Observation,
    Query,
    Response,
    observation_marks_instance_complete,
)
from ...registry import register_system
from ..utils import (
    TokenBudgetTracker,
    completion_with_structured_output,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_ENDPOINT = "http://127.0.0.1:3320"
DEFAULT_TOP_K = 6

RESPONSE_SYSTEM_PROMPT = """\
You are an agent working on a continual learning benchmark task. You have \
access to a memory store of lessons distilled from past instances of this \
task. These lessons capture recurring structure (opponent tendencies, schema \
conventions, environment quirks) that you should reuse when relevant.

Use the lessons to inform your response, but treat them as beliefs, not \
commands. If a lesson seems contradicted by the current observation, trust the \
current observation and your reasoning."""

MEMORY_BLOCK_HEADER = "=== LESSONS FROM PRIOR EXPERIENCE ==="
MEMORY_BLOCK_FOOTER = "======================================="


# ---------------------------------------------------------------------------
# Helpers (no I/O)
# ---------------------------------------------------------------------------


def _parse_outcome(content: str) -> Optional[str]:
    """Best-effort classify a completed-instance observation as won/lost/tied.

    Poker hand-end observations look like:
        "Hand 3 complete: You WON! ..."
        "Hand 4 complete: You LOST! ..."
        "Hand 5 complete: You TIED! ..."
    """
    c = content.upper()
    # Match whole-word outcome tokens at hand-completion lines.
    if re.search(r"\bWON\b", c):
        return "won"
    if re.search(r"\bLOST\b", c):
        return "lost"
    if re.search(r"\bTIED\b", c):
        return "tied"
    return None


def _extract_opponent(prompt: str) -> Optional[str]:
    """Extract the opponent name from a poker prompt."""
    for line in prompt.split("\n"):
        if "Opponent:" in line:
            rest = line.split("Opponent:")[1].strip()
            return rest.split()[0] if rest else None
    return None


def _distill_lesson_text(prompt: str, action_str: str, feedback: str) -> str:
    """Distill a completed hand into a STRATEGIC opponent-model lesson.

    The key insight: poker hands have unique cards, but opponent BEHAVIOR is
    deterministic. The lesson captures what the opponent DID across the betting
    rounds — did they reach showdown (never fold), what did they show down
    (strong/weak), and what streets were seen. These signals reveal the fixed
    policy and are reusable across all future hands against the same opponent.
    """
    import json as _json
    opponent = _extract_opponent(prompt) or "unknown"

    # Parse the agent's action from the last step
    agent_action = "?"
    try:
        ad = _json.loads(action_str) if isinstance(action_str, str) else {}
        agent_action = ad.get("action", "?")
    except Exception:
        pass

    feedback_lower = feedback.lower()

    # Core strategic signals from the feedback:
    # 1. Did the hand reach showdown? (opponent never folds = calling station)
    # 2. What did they show? (strong/weak hand at showdown)
    # 3. How many streets were played? (from board card count)
    reached_showdown = "showdown" in feedback_lower

    # Extract opponent's shown hand if available
    opp_shown = ""
    for line in feedback.split("\n"):
        if "opponent" in line.lower() and "hand" in line.lower():
            opp_shown = line.strip()
            break

    # Count streets from board (preflop=0, flop=3, turn=4, river=5)
    streets = 0
    for line in feedback.split("\n"):
        if "board:" in line.lower() and "showdown" not in line.lower():
            card_count = line.count("[")
            streets = min(card_count, 5)
            break
    # Also check showdown board
    if streets == 0:
        for line in feedback.split("\n"):
            if "board:" in line.lower():
                card_count = line.count("[")
                streets = min(card_count, 5)
                break

    # Outcome
    outcome = "unknown"
    if "won" in feedback_lower:
        outcome = "won"
    elif "lost" in feedback_lower:
        outcome = "lost"
    elif "tied" in feedback_lower:
        outcome = "tied"

    # Net chip change
    net_change = ""
    for line in feedback.split("\n"):
        if "net chip change" in line.lower():
            net_change = line.strip()
            break

    # Build a concise strategic summary
    parts = [f"Opponent {opponent}:"]
    if reached_showdown:
        parts.append(f"reached showdown (saw {streets} board cards, never folded)")
    else:
        parts.append("hand ended before showdown")
    if opp_shown:
        parts.append(opp_shown)
    parts.append(f"my last action: {agent_action}")
    parts.append(f"result: {outcome}. {net_change}")

    return ". ".join(parts)


def _build_retrieval_key(prompt: str, last_turn_feedback: Optional[str]) -> str:
    """Build the query used to retrieve relevant lessons.

    For poker, the retrieval key is just the opponent name — we want ALL
    strategic lessons about this opponent, not lessons that happened to involve
    similar cards (which are irrelevant since cards change every hand).
    """
    opponent = _extract_opponent(prompt)
    if opponent:
        return f"Opponent {opponent} strategy tendencies behavior calling folding raising"
    # Non-poker fallback: use the prompt directly.
    return prompt[:300]


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@register_system("mubit")
class MubitMemorySystem(ContinualLearningSystem):
    """
    Mubit-backed memory system.

    On each completed instance, the (prompt, action, feedback) triple is
    distilled into a lesson and written to Mubit via ``remember()``. On each
    turn, relevant lessons are retrieved via ``recall()`` and injected into the
    prompt. Memory persists across instances within a run (one Mubit run_id)
    and is naturally isolated across the stateless baseline, which constructs
    a fresh system (and run_id) per instance.
    """

    supports_baseline: bool = True
    parallel_safe: bool = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        share_scope: str = "run",
    ):
        """
        Args:
            model: LiteLLM model for task responses.
            top_k: Number of lessons to retrieve per turn.
            system_prompt: Extra system prompt content appended to the base.
            max_tokens: Optional max output tokens for the LLM.
            share_scope: Lesson scope for Mubit writes ("run" | "session" |
                "global"). "run" keeps lessons within the current run_id only.
        """
        self.model = model
        self.top_k = top_k
        self.user_system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.share_scope = share_scope

        # Conversation context (within current instance only).
        self.messages: list[dict[str, str]] = []
        self._token_budget = TokenBudgetTracker()

        # Tracking
        self.interaction_count: int = 0
        self._last_query: Optional[Query] = None
        self._last_response: Optional[Response] = None
        # Feedback from the previous turn within the current instance.
        self._last_turn_feedback: Optional[str] = None
        # True at the start of a new instance (hand) — controls when lessons
        # are injected. Set by observe() at instance completion, cleared by
        # respond() after the first turn of the new instance.
        self._at_instance_boundary: bool = True

        # Mubit client + run scoping (lazily connected so the class can be
        # introspected/imported without a running instance).
        self._client = None
        self._run_id: Optional[str] = None
        self._connect_client()

    # ---- Mubit connection ----

    def _connect_client(self) -> None:
        """Connect to the Mubit instance and assign a fresh run_id."""
        api_key = os.environ.get("MUBIT_API_KEY")
        endpoint = os.environ.get("MUBIT_ENDPOINT", DEFAULT_ENDPOINT)
        if not api_key:
            logger.warning(
                "MUBIT_API_KEY not set; Mubit system will run memoryless "
                "(retrieve nothing, store nothing)."
            )
            self._client = None
            self._run_id = None
            return
        try:
            # Import lazily so benchmark import doesn't require the SDK.
            from mubit import Client  # type: ignore

            self._client = Client(endpoint=endpoint)
            self._client.set_api_key(api_key)
            # Force HTTP transport — gRPC channels can stall in the
            # benchmark's per-instance client pattern.
            self._client.set_transport("http")
        except Exception:
            logger.warning(
                "Failed to connect to Mubit at %s; running memoryless.",
                endpoint,
                exc_info=True,
            )
            self._client = None
        self._new_run_id()

    def _new_run_id(self) -> None:
        """Assign a fresh run_id so memory is scoped to this system instance."""
        self._run_id = f"clbench-mubit-{uuid.uuid4().hex[:12]}"
        if self._client is not None:
            try:
                self._client.set_run_id(self._run_id)
            except Exception:
                logger.warning("Mubit set_run_id failed", exc_info=True)

    # ---- ContinualLearningSystem interface ----

    def respond(self, query: Query) -> Response:
        self.interaction_count += 1

        # Only retrieve/inject lessons at the START of a new instance (hand).
        # _at_instance_boundary is set True by observe() when the previous
        # instance completed, and cleared after the first respond() of the new
        # instance. This prevents injecting the same lessons on every betting
        # round within the same hand.
        if self._at_instance_boundary:
            retrieved = self._retrieve_lessons(query)
        else:
            retrieved = []
        self._at_instance_boundary = False
        query_content = self._inject_memory(query.prompt, retrieved)

        self._add_message("user", query_content)

        llm_messages = self.messages.copy()
        sys_parts = [RESPONSE_SYSTEM_PROMPT]
        if self.user_system_prompt:
            sys_parts.append(self.user_system_prompt)
        llm_messages.insert(0, {"role": "system", "content": "\n\n".join(sys_parts)})

        parsed, usage_event = completion_with_structured_output(
            model=self.model,
            messages=llm_messages,
            response_schema=query.response_schema,
        )
        assistant_record = parsed.model_dump_json()

        if usage_event is not None:
            self._note_prompt_token_usage(usage_event.input_tokens)
            self.record_usage_event(usage_event)

        self._add_message("assistant", assistant_record)

        retrieved_texts = [r.get("text", "") for r in retrieved if r.get("text")]
        # Expose entry ids + metadata for downstream subclasses (e.g. outcome
        # reinforcement in mubit_full) while keeping the human-readable texts.
        retrieved_meta = [
            {"id": r.get("id"), "text": r.get("text", ""), "metadata": r.get("metadata")}
            for r in retrieved
            if r.get("text")
        ]
        response = Response(
            action=parsed,
            metadata={
                "interaction_count": self.interaction_count,
                "system_type": "mubit",
                "model": self.model,
                "mubit_run_id": self._run_id,
                "retrieved_count": len(retrieved_texts),
                "retrieved_lessons": retrieved_texts[: DEFAULT_TOP_K],
                "retrieved_lessons_meta": retrieved_meta[: DEFAULT_TOP_K],
            },
        )
        self._last_query = query
        self._last_response = response
        return response

    def observe(
        self, observation: Observation, next_query: Optional[Query] = None
    ) -> None:
        instance_complete = observation_marks_instance_complete(observation)
        content = observation.content.strip()

        # Carry the last within-instance feedback forward for in-hand context.
        self._last_turn_feedback = content or None

        # Store a lesson only at instance completion, when we have a full
        # (prompt, action, feedback) triple and a definitive outcome.
        if instance_complete and self._last_query and self._last_response:
            self._write_lesson(self._last_query, self._last_response, content)

        # Add feedback to the in-hand conversation context.
        if content:
            self._add_message("user", f"FEEDBACK: {content}")

        # Clear per-instance conversation context at boundaries and flag the
        # next respond() to inject lessons (start of a new hand).
        if instance_complete:
            self.messages = []
            self._last_turn_feedback = None
            self._at_instance_boundary = True

    def reset(self) -> None:
        # Fresh run_id wipes effective memory for the baseline phase without
        # deleting server-side data (rollouts and baselines get distinct ids).
        self._new_run_id()
        self.messages = []
        self._token_budget.reset()
        self.interaction_count = 0
        self._last_query = None
        self._last_response = None
        self._last_turn_feedback = None
        self._at_instance_boundary = True

    @property
    def name(self) -> str:
        return "mubit"

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:
        return {
            "artifact_type": "mubit",
            "endpoint": os.environ.get("MUBIT_ENDPOINT", DEFAULT_ENDPOINT),
            "model": self.model,
            "top_k": self.top_k,
            "run_id": self._run_id,
        }

    # ---- internal ----

    def _add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def _retrieve_lessons(self, query: Query) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        key = _build_retrieval_key(query.prompt, self._last_turn_feedback)
        try:
            out = self._client.recall(
                query=key,
                limit=self.top_k,
                entry_types=["lesson"],
                include_working_memory=False,
            )
        except Exception:
            logger.warning("Mubit recall failed; proceeding memoryless", exc_info=True)
            return []
        evidence = out.get("evidence") or []
        # Normalise to a list of {id, text, metadata} dicts. The id is the
        # Mubit entry id, needed for outcome reinforcement in subclasses.
        norm: list[dict[str, Any]] = []
        for e in evidence:
            text = e.get("text") or e.get("content") or ""
            if not text:
                continue
            norm.append(
                {
                    "id": e.get("id") or e.get("entry_id") or e.get("item_id"),
                    "text": text,
                    "metadata": e.get("metadata") or {},
                }
            )
        return norm

    def _inject_memory(
        self, prompt: str, lessons: list[dict[str, Any]]
    ) -> str:
        if not lessons:
            return prompt
        lines = []
        for i, m in enumerate(lessons, 1):
            # Truncate each lesson to keep the block concise and scannable.
            text = m["text"][:300]
            lines.append(f"  {i}. {text}")
        block = f"{MEMORY_BLOCK_HEADER}\n" + "\n".join(lines) + f"\n{MEMORY_BLOCK_FOOTER}"
        return f"{block}\n\n{prompt}"

    def _write_lesson(
        self, query: Query, response: Response, feedback: str
    ) -> None:
        if self._client is None or not feedback:
            return
        action = response.action
        action_str = (
            action.model_dump_json()
            if isinstance(action, BaseModel)
            else str(action)
        )
        outcome = _parse_outcome(feedback) or "neutral"
        lesson_text = _distill_lesson_text(query.prompt, action_str, feedback)
        opponent = _extract_opponent(query.prompt) or "unknown"

        lesson_type = (
            "success" if outcome == "won" else "failure" if outcome == "lost" else "observation"
        )
        importance = "high" if outcome in ("won", "lost") else "medium"

        # Key by opponent + outcome so each opponent accumulates a running
        # model from wins and losses separately. Each new hand with the same
        # opponent+outcome overwrites, keeping the freshest strategic read.
        upsert_key = f"lesson:{opponent}:{outcome}"

        metadata: dict[str, Any] = {
            "task": "exploitable_poker",
            "opponent": opponent,
            "instance_id": query.instance_id,
            "instance_index": query.instance_index,
            "outcome": outcome,
        }

        try:
            self._client.remember(
                content=lesson_text,
                intent="lesson",
                lesson_type=lesson_type,
                lesson_scope=self.share_scope,
                lesson_importance=importance,
                upsert_key=upsert_key,
                metadata=metadata,
                source="agent",
                agent_id="clbench-mubit",
                wait=False,
            )
        except Exception:
            logger.warning("Mubit remember failed; lesson not stored", exc_info=True)

    # ---- token bookkeeping (mirrors mem0/icl_notepad) ----

    def _estimate_message_tokens(self, messages: list[dict[str, str]]) -> int:
        if not messages:
            return 0
        try:
            import litellm  # type: ignore

            return litellm.token_counter(model=self.model, messages=messages)
        except Exception:
            return sum(4 + len(m.get("content", "")) // 4 for m in messages) + 2

    def _note_prompt_token_usage(self, input_tokens: Optional[int]) -> None:
        self._token_budget.note_usage(
            messages=self.messages,
            input_tokens=input_tokens,
            estimate_fn=self._estimate_message_tokens,
        )
