"""Mubit system, instrumented for the live demo.

This is ``mubit`` with a wire tap. It subclasses :class:`MubitMemorySystem` and
changes **no** behaviour: the retrieval key, the lesson text, the injected
block, the upsert key and the metadata are all produced by the parent class,
untouched, including their known warts (the generic 200-char distiller on the
database task, and ``metadata["task"] == "exploitable_poker"`` on every write).
That is deliberate. The demo's live gain is only comparable to the committed
artifacts if the code path is the one that produced them.

What this adds is observation:

* :class:`_MubitWireTap` wraps the Mubit SDK client in a pure pass-through
  proxy and records the exact arguments and exact return value of every
  ``recall()`` and ``remember()``. The "what Mubit gets / what Mubit gives"
  screen is literally this wire, not a reconstruction of it.
* ``respond`` / ``observe`` are overridden to bracket the parent call and emit
  the surrounding turn structure (question start, injected block, model
  latency, environment feedback).

Two invariants hold everywhere in this file:

1. **No instrumentation failure may affect the run.** Every emit path is
   wrapped; the emitter drops events rather than blocking; if the collector is
   down or absent the system behaves exactly like ``mubit``.
2. **No intercepted call may alter its own semantics.** The tap forwards
   ``*args, **kwargs`` verbatim and returns the callee's value unmodified;
   exceptions propagate unchanged after being recorded.

Configuration (all optional — unset means "run silently, like ``mubit``"):
  MUBIT_DEMO_COLLECTOR   Base URL of the demo collector, e.g. http://127.0.0.1:8799
  MUBIT_DEMO_DRIFT_INDEX Instance index at which the schema migration lands (default 10)
"""

from __future__ import annotations

import atexit
import inspect
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

from ...registry import register_system
from ..mubit.system import DEFAULT_MODEL, DEFAULT_TOP_K, MubitMemorySystem

# The migration notice the database task prepends to the first post-drift
# prompt (src/tasks/database_exploration/task.py). Matching on it is how the
# demo knows the drift landed on this exact turn rather than inferring it.
DRIFT_NOTICE_PREFIX = "NOTICE: The live database schema or contents may have"

_MAX_QUEUED_EVENTS = 4096
_POST_TIMEOUT_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


class _Emitter:
    """Fire-and-forget event sink with a bounded queue and a worker thread.

    One per process. ``emit`` never blocks and never raises: if the queue is
    full the event is dropped and a counter is bumped, because a stalled demo
    pane is an acceptable outcome and a stalled benchmark is not.
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/") + "/event"
        self._q: queue.Queue = queue.Queue(maxsize=_MAX_QUEUED_EVENTS)
        self._seq = 0
        self._lock = threading.Lock()
        self.dropped = 0
        self._thread = threading.Thread(
            target=self._pump, name="mubit-demo-emitter", daemon=True
        )
        self._thread.start()
        atexit.register(self.flush)

    def emit(self, event: dict) -> None:
        try:
            with self._lock:
                self._seq += 1
                event["seq"] = self._seq
            event["ts"] = time.time()
            self._q.put_nowait(event)
        except queue.Full:
            self.dropped += 1
        except Exception:
            pass

    def _pump(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            try:
                body = json.dumps(item, default=str).encode("utf-8")
                req = urllib.request.Request(
                    self._url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=_POST_TIMEOUT_SECONDS).close()
            except (urllib.error.URLError, OSError, ValueError):
                pass
            except Exception:
                pass
            finally:
                self._q.task_done()

    def flush(self, timeout: float = 3.0) -> None:
        """Best-effort drain at process exit so the last events aren't lost."""
        deadline = time.time() + timeout
        while not self._q.empty() and time.time() < deadline:
            time.sleep(0.02)


def _make_emitter() -> Optional[_Emitter]:
    base = os.environ.get("MUBIT_DEMO_COLLECTOR")
    if not base:
        return None
    try:
        return _Emitter(base)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Wire tap
# ---------------------------------------------------------------------------


def _trim(value: Any, limit: int = 4000) -> Any:
    """Bound a payload for transport without silently pretending it was short."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"… [+{len(value) - limit} chars]"
    return value


class _MubitWireTap:
    """Transparent proxy around the Mubit SDK client.

    Attribute access falls through to the wrapped client, so anything this
    class does not name explicitly behaves as if the tap were not here. Only
    ``recall`` and ``remember`` are intercepted, and only to record their
    arguments, their return value and their latency.
    """

    def __init__(self, client: Any, on_event) -> None:
        object.__setattr__(self, "_tap_client", client)
        object.__setattr__(self, "_tap_on_event", on_event)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_tap_client"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_tap_client"), name, value)

    # -- intercepted calls --------------------------------------------------

    def recall(self, *args: Any, **kwargs: Any) -> Any:
        client = object.__getattribute__(self, "_tap_client")
        fire = object.__getattribute__(self, "_tap_on_event")
        fire("recall.request", {"args": [_trim(a) for a in args], "kwargs": _kw(kwargs)})
        t0 = time.perf_counter()
        try:
            out = client.recall(*args, **kwargs)
        except Exception as exc:
            fire(
                "recall.response",
                {
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": f"{type(exc).__name__}: {exc}",
                    "evidence": [],
                    "count": 0,
                },
            )
            raise
        fire(
            "recall.response",
            {
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "count": len(((out or {}).get("evidence")) or []),
                "evidence": _evidence(out),
                "raw_keys": sorted((out or {}).keys()) if isinstance(out, dict) else None,
            },
        )
        return out

    def remember(self, *args: Any, **kwargs: Any) -> Any:
        client = object.__getattribute__(self, "_tap_client")
        fire = object.__getattribute__(self, "_tap_on_event")
        fire("remember.request", {"args": [_trim(a) for a in args], "kwargs": _kw(kwargs)})
        t0 = time.perf_counter()
        try:
            out = client.remember(*args, **kwargs)
        except Exception as exc:
            fire(
                "remember.response",
                {
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise
        fire(
            "remember.response",
            {
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "result": _trim(out if isinstance(out, (dict, str, int, float)) else str(out)),
            },
        )
        return out


def _kw(kwargs: dict) -> dict:
    return {k: _trim(v) for k, v in kwargs.items()}


def _evidence(out: Any) -> list[dict]:
    """Normalise a recall result to what the ledger and store screens show.

    Field names are read defensively: this is the SDK's shape, not ours, and a
    missing score must show as absent rather than as zero.
    """
    if not isinstance(out, dict):
        return []
    rows = []
    for e in (out.get("evidence") or []):
        if not isinstance(e, dict):
            continue
        rows.append(
            {
                "id": e.get("id") or e.get("entry_id") or e.get("item_id"),
                "text": _trim(e.get("text") or e.get("content") or "", 1200),
                "score": e.get("score", e.get("similarity", e.get("relevance"))),
                "metadata": e.get("metadata") or {},
                "created_at": e.get("created_at") or e.get("timestamp"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


def _detect_arm() -> str:
    """Return "stateful" or "stateless" for the arm this process is running.

    CL-Bench gives the system no phase marker: ``phase`` reaches the trace
    recorder but never the system, and both arms are constructed with identical
    ``system_params``. The one unambiguous signal available at construction
    time is the caller — the stateless baseline builds its system inside
    ``_run_baseline_instance`` (src/runs/baseline.py) and the stateful rollout
    inside ``run_single`` (src/runs/single.py).

    Read-only stack introspection, so it cannot perturb the run. If CL-Bench
    ever renames those functions this degrades to "unknown", which the pages
    render as an explicitly unattributed lane rather than guessing.
    """
    try:
        for frame in inspect.stack()[1:14]:
            fn = frame.function
            if fn == "_run_baseline_instance":
                return "stateless"
            if fn in ("run_single", "_run_benchmark_run"):
                return "stateful"
    except Exception:
        pass
    return "unknown"


@register_system("mubit_demo")
class MubitDemoSystem(MubitMemorySystem):
    """``mubit`` plus event emission. No behavioural difference."""

    supports_baseline: bool = True
    parallel_safe: bool = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        top_k: int = DEFAULT_TOP_K,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        share_scope: str = "run",
    ) -> None:
        # The signature mirrors MubitMemorySystem's exactly rather than
        # forwarding *args/**kwargs. CL-Bench builds its `--system.<param>`
        # flags by introspecting this constructor (cli.py add_class_params), so
        # a variadic signature would silently drop `--system.model` and run the
        # wrong model while appearing to succeed.
        self._emitter = _make_emitter()
        self._arm = _detect_arm()
        self._emitter_id = uuid.uuid4().hex[:12]
        self._instance_index: Optional[int] = None
        self._instance_id: Optional[str] = None
        self._turn: int = 0
        try:
            self._drift_index = int(os.environ.get("MUBIT_DEMO_DRIFT_INDEX", "10"))
        except ValueError:
            self._drift_index = 10

        # Parent __init__ connects the client; the tap goes on afterwards so
        # the connection sequence itself is unchanged.
        super().__init__(
            model=model,
            top_k=top_k,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            share_scope=share_scope,
        )

        if self._client is not None and self._emitter is not None:
            self._client = _MubitWireTap(self._client, self._fire)

        self._fire(
            "system.ready",
            {
                "arm": self._arm,
                "model": self.model,
                "top_k": self.top_k,
                "share_scope": self.share_scope,
                "mubit_run_id": self._run_id,
                "connected": self._client is not None,
            },
        )

    @property
    def name(self) -> str:
        return "mubit_demo"

    # -- emission -----------------------------------------------------------

    def _fire(self, kind: str, payload: dict) -> None:
        if self._emitter is None:
            return
        try:
            self._emitter.emit(
                {
                    "type": kind,
                    "arm": self._arm,
                    "emitter": self._emitter_id,
                    "pid": os.getpid(),
                    "mubit_run_id": self._run_id,
                    "instance_index": self._instance_index,
                    "instance_id": self._instance_id,
                    "stage": self._stage(),
                    "turn": self._turn,
                    "payload": payload,
                }
            )
        except Exception:
            pass

    def _stage(self) -> Optional[str]:
        if self._instance_index is None:
            return None
        return "post" if self._instance_index >= self._drift_index else "pre"

    def _last_usage(self) -> Optional[dict]:
        """Peek — never consume — the newest usage event the parent recorded."""
        try:
            events = getattr(self, "_usage_events", None) or []
            if not events:
                return None
            e = events[-1]
            return {
                "model": getattr(e, "model", None),
                "input_tokens": getattr(e, "input_tokens", None),
                "output_tokens": getattr(e, "output_tokens", None),
                "total_tokens": getattr(e, "total_tokens", None),
                "cost_usd": getattr(e, "cost_usd", None),
            }
        except Exception:
            return None

    # -- instrumented overrides --------------------------------------------

    def respond(self, query):  # type: ignore[override]
        new_instance = self._at_instance_boundary
        if new_instance:
            self._instance_index = query.instance_index
            self._instance_id = query.instance_id
            self._turn = 0
            md = query.metadata or {}
            drifted = DRIFT_NOTICE_PREFIX in (query.prompt or "")
            if drifted:
                self._fire("stage.change", {"notice": DRIFT_NOTICE_PREFIX})
            self._fire(
                "instance.start",
                {
                    "question_id": md.get("question_id"),
                    "question_num": md.get("question_num"),
                    "difficulty": md.get("difficulty"),
                    "query_budget": md.get("query_budget"),
                    "db_path": md.get("db_path"),
                    "prompt": _trim(query.prompt, 6000),
                    "carries_drift_notice": drifted,
                },
            )
        self._turn += 1
        self._fire(
            "turn.start",
            {
                "queries_used": (query.metadata or {}).get("queries_used"),
                "prompt_chars": len(query.prompt or ""),
                "will_retrieve": new_instance,
            },
        )

        t0 = time.perf_counter()
        response = super().respond(query)
        elapsed = round((time.perf_counter() - t0) * 1000, 1)

        action = getattr(response, "action", None)
        self._fire(
            "llm.response",
            {
                "latency_ms": elapsed,
                "action": getattr(action, "action", None),
                "content": _trim(getattr(action, "content", "") or "", 4000),
                "retrieved_count": (response.metadata or {}).get("retrieved_count"),
                "usage": self._last_usage(),
            },
        )
        return response

    def _inject_memory(self, prompt: str, lessons: list[dict[str, Any]]) -> str:  # type: ignore[override]
        out = super()._inject_memory(prompt, lessons)
        self._fire(
            "prompt.injected",
            {
                "lesson_count": len(lessons),
                "injected": out != prompt,
                "block": _trim(out[: len(out) - len(prompt)], 4000) if out != prompt else "",
                "chars_added": len(out) - len(prompt),
                "prompt_chars": len(prompt),
            },
        )
        return out

    def observe(self, observation, next_query=None) -> None:  # type: ignore[override]
        content = (observation.content or "").strip()
        complete = bool(getattr(observation, "instance_complete", False))
        self._fire(
            "env.feedback",
            {
                "content": _trim(content, 4000),
                "instance_complete": complete,
                "metadata": observation.metadata or {},
            },
        )
        super().observe(observation, next_query)
        if complete:
            self._fire("instance.end", {"turns": self._turn})

    def reset(self) -> None:  # type: ignore[override]
        super().reset()
        self._instance_index = None
        self._instance_id = None
        self._turn = 0
        self._fire("system.reset", {"mubit_run_id": self._run_id})

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:  # type: ignore[override]
        out = super().get_run_artifacts() or {}
        out["artifact_type"] = "mubit_demo"
        out["demo_arm"] = self._arm
        out["demo_emitter"] = self._emitter_id
        if self._emitter is not None:
            out["demo_events_dropped"] = self._emitter.dropped
        return out
