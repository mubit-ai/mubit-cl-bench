"""Mubit BSM system: the transmitter registry, stored in Mubit.

Instead of prose lessons, this system accumulates a **structured transmitter
registry** — one Mubit entry, upserted on a stable key and refined by each
scan. That addresses the two BSM failure modes:

1. Under-reporting: dormant channels stay in the registry even when they are
   not in the current scan, so the agent always knows about them.
2. Fragmentation: near-duplicate frequency observations merge into one entry,
   so 13 real transmitters are not reported as 18.

The registry is read back with ``lookup()`` at the start of each scan and
injected as structured context the LLM can turn straight into a ScanReport —
no lossy prose-to-JSON round trip. Grid inference is derived from what was
read and is never written back; memory holds observations only.

Non-BSM prompts fall through to ``mubit_genai`` unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from ...interface import Observation, Query, Response, observation_marks_instance_complete
from ...registry import register_system
from ..mubit_genai.system import MubitGenAISystem
from .registry import (
    REGISTRY_KEY,
    REGISTRY_MATCH,
    dedupe,
    dumps_registry,
    extract_peaks,
    format_registry,
    infer_grid_channels,
    is_bsm,
    is_wideband,
    loads_registry,
    merge_peaks,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"

# One registry entry is written per scan (the upsert supersedes rather than
# replaces), so this covers a 90-scan run with room to spare.
# ponytail: fixed cap, paginate if a schedule ever runs longer than this.
LOOKUP_LIMIT = 256

BSM_SYSTEM_PROMPT = """\
You are a spectrum monitoring analyst. You receive RF scan data and must \
report ALL persistent transmitters in the band, including dormant ones not \
visible in the current scan.

Key insight: transmitters follow a regular grid pattern. Wideband channels \
are spaced 24 MHz apart (center = slot × 24 + 7.5 MHz, bandwidth = 15 MHz). \
Narrowband channels (bandwidth = 5 MHz) sit inside the guard gaps between \
wideband channels.

If you have observed wideband channels at slots 0-4, you should INFER that \
slots 5 and 6 likely also exist (at 127.5 and 151.5 MHz), even if you haven't \
seen them yet. Similarly, if you see a narrowband at one guard gap, check all \
gaps for narrowbands.

The ACCUMULATED TRANSMITTER REGISTRY below contains every transmitter you have \
observed across all scans so far, with how many times each was seen. Use this \
as your primary evidence. Merge any new peaks from the current scan into this \
registry, then report all transmitters you believe persist in the band."""


@register_system("mubit_bsm")
class MubitBSMSystem(MubitGenAISystem):
    """Mubit-backed transmitter registry, with mubit_genai for other tasks."""

    supports_baseline = True
    parallel_safe = False  # inherited constraint: google-genai + fork

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        top_k: int = 6,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        share_scope: str = "run",
        temperature: float = 0.0,
    ):
        super().__init__(
            model=model,
            top_k=top_k,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            share_scope=share_scope,
            temperature=temperature,
        )
        self._scan_count: int = 0
        if self._client is None:
            logger.warning(
                "No Mubit client: the transmitter registry has nowhere to live, "
                "so BSM will run stateless."
            )

    @property
    def name(self) -> str:
        return "mubit_bsm"

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:
        base = super().get_run_artifacts() or {}
        base.update({"artifact_type": "mubit_bsm", "scan_count": self._scan_count})
        return base

    # ---- routing ----

    def respond(self, query: Query) -> Response:
        if is_bsm(query.prompt):
            return self._respond_bsm(query)
        return super().respond(query)

    def observe(self, observation: Observation, next_query: Optional[Query] = None) -> None:
        if self._last_query is not None and is_bsm(self._last_query.prompt):
            # The registry is the memory here; there is no lesson to distil.
            if observation.content.strip():
                self._add_message("user", f"FEEDBACK: {observation.content.strip()}")
            if observation_marks_instance_complete(observation):
                self.messages = []
            return
        super().observe(observation, next_query)

    def reset(self) -> None:
        # Fresh run_id, so the baseline arm recalls an empty registry.
        super().reset()
        self._scan_count = 0

    # ---- registry <-> Mubit ----

    def _load_registry(self) -> list[dict]:
        """Read the registry back out of Mubit with a deterministic lookup.

        Not ``recall()``: semantic search ranks and truncates (the server caps
        evidence at 50, and Mubit's own auto-reflection lessons compete for
        those slots), so transmitters flickered in and out between scans and
        lost their hit counts. ``lookup()`` enumerates straight from storage.
        """
        if self._client is None:
            return []
        try:
            records = self._client.lookup(match=[REGISTRY_MATCH], limit=LOOKUP_LIMIT)
        except Exception:
            logger.warning("Mubit lookup failed; scan runs registry-less", exc_info=True)
            return []
        newest, newest_scan = [], -1
        for record in records or []:
            metadata = record.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except ValueError:
                    continue
            entries, scan = loads_registry(metadata.get("content") or "")
            if entries and scan > newest_scan:
                newest, newest_scan = entries, scan
        return dedupe(newest)

    def _save_registry(self, registry: list[dict]) -> None:
        """Upsert the whole registry as one entry."""
        if self._client is None:
            return
        try:
            self._client.remember(
                content=dumps_registry(registry, self._scan_count),
                intent="fact",
                upsert_key=REGISTRY_KEY,
                metadata={
                    **REGISTRY_MATCH,
                    "scan": self._scan_count,
                    "transmitters": len(registry),
                },
                source="agent",
                agent_id="clbench-mubit-bsm",
                # Written at the end of one scan, read at the start of the
                # next — block so it is there by then.
                wait=True,
            )
        except Exception:
            logger.warning("Mubit remember failed for the registry", exc_info=True)

    # ---- BSM turn ----

    def _respond_bsm(self, query: Query) -> Response:
        self.interaction_count += 1
        self._scan_count += 1

        registry = self._load_registry()
        registry, changed = merge_peaks(registry, extract_peaks(query.prompt), self._scan_count)
        self._save_registry(registry)

        # Grid inference is a hypothesis over what was recalled: shown to the
        # model, never written back.
        view = infer_grid_channels(registry)

        self._add_message(
            "user",
            f"=== ACCUMULATED TRANSMITTER REGISTRY ===\n"
            f"{format_registry(view)}\n"
            f"=========================================\n\n"
            f"Current scan #{self._scan_count} peaks:\n{self._extract_scan_data(query.prompt)}\n\n"
            f"Report ALL transmitters from the registry (including inferred and "
            f"tentative ones). Also add any new peaks from the current scan that "
            f"aren't in the registry yet. Do NOT fragment a single transmitter "
            f"into multiple reports.",
        )

        parsed, usage_event = self._genai_completion(
            BSM_SYSTEM_PROMPT,
            self._to_genai_contents(self.messages),
            query.response_schema,
        )
        if usage_event is not None:
            self._note_prompt_token_usage(usage_event.input_tokens)
            self.record_usage_event(usage_event)

        parsed = self._filter_to_registry(parsed, view)
        self._add_message("assistant", parsed.model_dump_json())

        response = Response(
            action=parsed,
            metadata={
                "interaction_count": self.interaction_count,
                "system_type": "mubit_bsm",
                "model": self.model,
                "mubit_run_id": self._run_id,
                "registry_size": len(registry),
                "registry_written": len(changed),
                "scan_peaks": len(extract_peaks(query.prompt)),
            },
        )
        self._last_query = query
        self._last_response = response
        return response

    def _filter_to_registry(self, report: BaseModel, view: list[dict]) -> BaseModel:
        """Drop reported transmitters that match nothing in the registry.

        The LLM invents the occasional transmitter in an empty part of the band,
        and a false positive costs as much IoU as a miss. The registry is built
        from real observations, so this removes hallucinations rather than
        imposing an answer.
        """
        transmitters = getattr(report, "transmitters", None)
        if not view or not transmitters:
            return report
        kept = []
        for tx in transmitters:
            wide = tx.bandwidth >= 10
            threshold = 6.0 if wide else 4.0
            if any(
                is_wideband(e) == wide and abs(e["center_freq"] - tx.center_freq) < threshold
                for e in view
            ):
                kept.append(tx)
        return report.model_copy(update={"transmitters": kept})

    def _extract_scan_data(self, prompt: str) -> str:
        """Just the scan block, not the whole prompt."""
        idx = prompt.find("--- Scan")
        return prompt[idx:] if idx >= 0 else prompt[-500:]
