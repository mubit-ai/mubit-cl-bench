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
  MUBIT_ENDPOINT  HTTP endpoint (default https://api.mubit.ai).
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
from .schema import drift_fact, schema_fact

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_ENDPOINT = "https://api.mubit.ai"
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


def _detect_task(prompt: str) -> str:
    """Detect which CL-Bench task this prompt belongs to."""
    if "--- Scan" in prompt and "Detected peaks:" in prompt:
        return "bsm"
    if "Opponent:" in prompt and ("FOLD" in prompt or "CALL" in prompt or "RAISE" in prompt):
        return "poker"
    if "SQL" in prompt or "sqlite" in prompt.lower() or "exploratory queries" in prompt.lower():
        return "database"
    return "generic"


def _distill_bsm_lesson(prompt: str, action_str: str, feedback: str) -> str:
    """Distill a BSM scan into a transmitter-observation lesson.

    Extracts the detected peaks (what the agent SAW this scan) and the
    transmitters the agent REPORTED. These accumulate across scans to build
    a running map of the persistent channel set — including dormant channels
    that aren't visible in every scan.
    """
    import json as _json
    import re

    # Extract detected peaks from the prompt
    peaks = []
    for match in re.finditer(r"freq:\s*([\d.]+)\s*MHz.*?power:\s*([-\d.]+)\s*dBm.*?width:\s*([\d.]+)\s*MHz", prompt):
        peaks.append({"freq": float(match.group(1)), "power": float(match.group(2)), "width": float(match.group(3))})

    # Extract scan number
    scan_num = "?"
    m = re.search(r"Scan (\d+)/", prompt)
    if m:
        scan_num = m.group(1)

    # Parse the agent's reported transmitters
    reported = []
    try:
        ad = _json.loads(action_str) if isinstance(action_str, str) else {}
        for tx in ad.get("transmitters", []):
            reported.append(f"{tx.get('center_freq','?')}MHz/{tx.get('bandwidth','?')}MHz")
    except Exception:
        pass

    peak_strs = [f"{p['freq']:.1f}MHz/{p['width']:.0f}MHz/{p['power']:.0f}dBm" for p in peaks]
    reported_strs = reported[:10]  # cap

    return (
        f"Scan {scan_num}: detected {len(peaks)} peaks: [{', '.join(peak_strs[:8])}]. "
        f"Reported {len(reported)} transmitters: [{', '.join(reported_strs[:8])}]. "
        f"Accumulate dormant channels — they may not appear in every scan."
    )


def _distill_lesson_text(prompt: str, action_str: str, feedback: str) -> str:
    """Task-aware lesson distillation.

    Detects the task type and delegates to the appropriate distiller. For
    tasks without a specialised distiller, falls back to a generic summary.
    """
    task = _detect_task(prompt)

    if task == "bsm":
        return _distill_bsm_lesson(prompt, action_str, feedback)

    if task == "poker":
        return _distill_poker_lesson(prompt, action_str, feedback)

    # Generic fallback
    return _distill_generic_lesson(prompt, action_str, feedback)


def _distill_poker_lesson(prompt: str, action_str: str, feedback: str) -> str:
    """Poker-specific strategic lesson (see _distill_lesson_text docs)."""
    import json as _json
    opponent = _extract_opponent(prompt) or "unknown"

    agent_action = "?"
    try:
        ad = _json.loads(action_str) if isinstance(action_str, str) else {}
        agent_action = ad.get("action", "?")
    except Exception:
        pass

    feedback_lower = feedback.lower()
    reached_showdown = "showdown" in feedback_lower

    opp_shown = ""
    for line in feedback.split("\n"):
        if "opponent" in line.lower() and "hand" in line.lower():
            opp_shown = line.strip()
            break

    outcome = "unknown"
    if "won" in feedback_lower:
        outcome = "won"
    elif "lost" in feedback_lower:
        outcome = "lost"

    net_change = ""
    for line in feedback.split("\n"):
        if "net chip change" in line.lower():
            net_change = line.strip()
            break

    parts = [f"Opponent {opponent}:"]
    if reached_showdown:
        parts.append("reached showdown (never folded)")
    else:
        parts.append("hand ended before showdown")
    if opp_shown:
        parts.append(opp_shown)
    parts.append(f"my last action: {agent_action}")
    parts.append(f"result: {outcome}. {net_change}")
    return ". ".join(parts)


def _distill_generic_lesson(prompt: str, action_str: str, feedback: str) -> str:
    """Generic lesson distiller for tasks without specialised logic."""
    action_short = action_str[:200] if isinstance(action_str, str) else str(action_str)[:200]
    feedback_short = feedback[:200] if feedback else ""
    return f"Prior instance feedback: {feedback_short}. My action: {action_short}"


def _build_retrieval_key(prompt: str, last_turn_feedback: Optional[str]) -> str:
    """Build the query used to retrieve relevant lessons.

    Task-aware: for poker, key on opponent name; for BSM, key on the current
    scan's detected peaks (to find prior scans with similar transmitters);
    for other tasks, use the prompt directly.
    """
    task = _detect_task(prompt)
    if task == "poker":
        opponent = _extract_opponent(prompt)
        if opponent:
            return f"Opponent {opponent} strategy tendencies behavior calling folding raising"
    if task == "bsm":
        # Use the detected peaks from this scan as the retrieval key — this
        # surfaces prior scans that observed similar frequencies.
        import re
        freqs = re.findall(r"freq:\s*([\d.]+)\s*MHz", prompt)
        if freqs:
            return f"Spectrum scan detected peaks at: {', '.join(freqs[:8])} MHz. Transmitter observations."
        return "Spectrum monitoring transmitter observations dormant channels"
    if task == "database":
        # Key on the schema, not the question. Every question is different;
        # the schema is the only thing that carries over between them.
        return (
            "database schema: table names, column names and types, which tables "
            "belong to which dataset, schema drift corrections"
        )
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
        # Schema facts written this run, keyed by object -> text. Re-writes
        # only go out when the text changed, so a migration refreshes the entry
        # and a repeat lookup costs nothing.
        self._schema_facts: dict[str, str] = {}

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

        # Database exploration: the durable artifact is the schema, and it is
        # discovered mid-instance, not at instance completion.
        if self._last_query is not None and _detect_task(self._last_query.prompt) == "database":
            self._harvest_schema(content)

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
        self._schema_facts = {}

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
        # A schema needs more slots than a handful of prose lessons.
        limit = 16 if _detect_task(query.prompt) == "database" else self.top_k
        try:
            out = self._client.recall(
                query=key,
                limit=limit,
                entry_types=["lesson"],
                include_working_memory=False,
                # Direct bypass: only ``evidence`` is used below, so skip the
                # agent router and the server-side answer synthesis. Measured
                # on a 50-entry store: 46s (gateway 504) -> 0.5s, and none of
                # the synthesis tokens are billed.
                mode="direct_bypass",
                evidence_only=True,
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
            # Schema facts are already capped at harvest (MAX_FACT_CHARS); a
            # second cap here would just move the truncation, not remove it.
            text = m["text"] if m["text"].startswith("SCHEMA") else m["text"][:300]
            lines.append(f"  {i}. {text}")
        if any(m["text"].startswith("SCHEMA") for m in lessons):
            # Without this the model re-runs PRAGMA out of habit, which is the
            # entire cost being optimised here.
            lines.append(
                "  You already know the above. Do not spend queries "
                "rediscovering it — explore only objects not listed here, or "
                "when a query errors."
            )
        block = f"{MEMORY_BLOCK_HEADER}\n" + "\n".join(lines) + f"\n{MEMORY_BLOCK_FOOTER}"
        return f"{block}\n\n{prompt}"

    def _write_lesson(
        self, query: Query, response: Response, feedback: str
    ) -> None:
        if self._client is None or not feedback:
            return
        task_type = _detect_task(query.prompt)
        if task_type == "database":
            # Schema facts written by _harvest_schema are the durable artifact
            # here; a prose summary of the previous *question* only crowds recall.
            return
        action = response.action
        action_str = (
            action.model_dump_json()
            if isinstance(action, BaseModel)
            else str(action)
        )
        outcome = _parse_outcome(feedback) or "neutral"
        lesson_text = _distill_lesson_text(query.prompt, action_str, feedback)
        opponent = _extract_opponent(query.prompt) if task_type == "poker" else None

        lesson_type = (
            "success" if outcome == "won" else "failure" if outcome == "lost" else "observation"
        )
        importance = "high" if outcome in ("won", "lost") else "medium"

        # Task-aware upsert key.
        if task_type == "poker":
            upsert_key = f"lesson:{opponent or 'unknown'}:{outcome}"
        else:
            # BSM and generic: key by instance_id so each scan/instance gets
            # its own lesson (they accumulate, don't overwrite).
            upsert_key = f"lesson:{query.instance_id or uuid.uuid4().hex[:8]}"

        metadata: dict[str, Any] = {
            "task": task_type,
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

    def _harvest_schema(self, observation: str) -> None:
        """Store what this query taught us about the database — or that the
        schema moved under us."""
        if self._client is None or not observation:
            return
        action = getattr(self._last_response, "action", None)
        sql = str(getattr(action, "content", "") or "")
        fact = drift_fact(observation) or schema_fact(sql, observation)
        if fact is None or self._schema_facts.get(fact[0]) == fact[1]:
            return
        upsert_key, text = fact
        self._schema_facts[upsert_key] = text
        try:
            self._client.remember(
                content=text,
                intent="lesson",
                lesson_type="observation",
                lesson_scope=self.share_scope,
                lesson_importance="high",
                upsert_key=upsert_key,
                metadata={"task": "database_exploration", "fact": upsert_key},
                source="agent",
                agent_id="clbench-mubit",
                # Written mid-instance, read at the next instance boundary —
                # block so the fact is queryable by then.
                wait=True,
            )
        except Exception:
            logger.warning("Mubit remember failed for %s", upsert_key, exc_info=True)

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
