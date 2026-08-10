"""
Mubit BSM-optimized system: structured transmitter registry.

Instead of storing prose lessons in Mubit and retrieving them, this system
maintains a **structured transmitter registry** — a deduplicated JSON list of
all transmitter hypotheses accumulated across scans. This directly addresses
the two failure modes identified in BSM analysis:

1. Under-reporting: dormant channels accumulate in the registry even when not
   visible in the current scan, so the agent always knows about them.
2. Fragmentation: near-duplicate frequency observations merge into one entry,
   preventing the agent from reporting 18 fragmented transmitters when the
   ground truth is 13.

The registry is injected as structured context that the LLM can directly use
to form its ScanReport — no lossy prose-to-JSON round-trip.

For non-BSM tasks, this system falls back to the base mubit_genai adapter.
"""

from __future__ import annotations

import json
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
from ...usage import UsageEvent

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"

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


def _extract_peaks(prompt: str) -> list[dict]:
    """Extract detected peaks from a BSM scan prompt."""
    peaks = []
    for match in re.finditer(
        r"freq:\s*([\d.]+)\s*MHz.*?power:\s*([-\d.]+)\s*dBm.*?width:\s*([\d.]+)\s*MHz",
        prompt,
    ):
        peaks.append(
            {
                "freq": float(match.group(1)),
                "power": float(match.group(2)),
                "width": float(match.group(3)),
            }
        )
    return peaks


def _is_bsm(prompt: str) -> bool:
    return "--- Scan" in prompt and "Detected peaks:" in prompt


def _merge_into_registry(
    registry: list[dict],
    peaks: list[dict],
    scan_num: int,
    merge_threshold: float = 8.0,
) -> list[dict]:
    """Merge detected peaks into the transmitter registry.

    Peaks within `merge_threshold` MHz of an existing entry are merged
    (averaging the center frequency, incrementing hit_count). New peaks
    create new entries.

    Wideband peaks (width >= 10) and narrowband peaks (width < 10) are
    kept in separate frequency bins to avoid merging a wideband with a
    nearby narrowband.
    """
    for peak in peaks:
        freq = peak["freq"]
        width = peak["width"]
        power = peak["power"]
        is_wideband = width >= 10.0

        # Find a match in the registry
        best_idx = -1
        best_dist = float("inf")
        for i, entry in enumerate(registry):
            # Don't merge wideband with narrowband
            entry_is_wide = entry["bandwidth"] >= 10.0
            if entry_is_wide != is_wideband:
                continue
            dist = abs(entry["center_freq"] - freq)
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx >= 0 and best_dist < merge_threshold:
            # Merge: update running average and increment count
            entry = registry[best_idx]
            old_count = entry["hit_count"]
            new_count = old_count + 1
            entry["center_freq"] = round(
                (entry["center_freq"] * old_count + freq) / new_count, 2
            )
            entry["bandwidth"] = round(
                (entry["bandwidth"] * old_count + width) / new_count, 1
            )
            entry["hit_count"] = new_count
            entry["last_seen_scan"] = scan_num
        else:
            # New transmitter hypothesis
            registry.append(
                {
                    "center_freq": round(freq, 2),
                    "bandwidth": round(width, 1),
                    "hit_count": 1,
                    "first_seen_scan": scan_num,
                    "last_seen_scan": scan_num,
                    "is_wideband": is_wideband,
                }
            )

    # Sort by center frequency
    registry.sort(key=lambda e: e["center_freq"])
    return registry


def _format_registry(registry: list[dict]) -> str:
    """Format the transmitter registry as a clean structured block."""
    if not registry:
        return "(no transmitters accumulated yet)"

    lines = []
    for entry in registry:
        cf = entry["center_freq"]
        bw = entry["bandwidth"]
        hits = entry["hit_count"]
        wb = "W" if entry.get("is_wideband", bw >= 10) else "N"
        confirmed = "confirmed" if hits >= 2 else "tentative"
        lines.append(
            f"  {cf:>7.1f} MHz | bw={bw:>5.1f} | hits={hits:>2} | {wb} | {confirmed}"
        )
    return "\n".join(lines)


def _infer_grid_channels(registry: list[dict]) -> list[dict]:
    """Infer missing wideband channels by grid regularity.

    If we have wideband entries at known slots, infer missing slots at
    slot*24+7.5 MHz. Only infer if at least 3 wideband channels are confirmed
    (hit_count >= 2) and the grid spacing is detectable.
    """
    widebands = [e for e in registry if e.get("is_wideband", e["bandwidth"] >= 10)]
    confirmed_wide = [e for e in widebands if e["hit_count"] >= 2]

    if len(confirmed_wide) < 3:
        return registry

    # Detect grid spacing: find the most common gap between consecutive widebands
    confirmed_wide.sort(key=lambda e: e["center_freq"])
    gaps = []
    for i in range(1, len(confirmed_wide)):
        gap = confirmed_wide[i]["center_freq"] - confirmed_wide[i - 1]["center_freq"]
        gaps.append(round(gap))

    if not gaps:
        return registry

    # Most common gap (should be ~24)
    from collections import Counter

    grid = Counter(gaps).most_common(1)[0][0]
    if grid < 18 or grid > 30:
        return registry  # Not a recognizable grid

    # Find the base offset (should be ~7.5)
    first_freq = confirmed_wide[0]["center_freq"]
    # Round to nearest grid slot
    base_slot = round((first_freq - 7.5) / grid)
    base_freq = base_slot * grid + 7.5

    # Infer all slots from min to max+2
    min_slot = base_slot
    max_slot = base_slot
    existing_slots = set()
    for e in confirmed_wide:
        slot = round((e["center_freq"] - base_freq) / grid) + base_slot
        existing_slots.add(slot)
        max_slot = max(max_slot, slot)
        min_slot = min(min_slot, slot)

    # Add inferred entries for missing slots
    for slot in range(min_slot, max_slot + 3):
        if slot not in existing_slots:
            inferred_freq = slot * grid + 7.5
            # Don't infer outside the band (0-168 MHz)
            if 0 <= inferred_freq <= 168:
                # Check we don't already have a close entry
                too_close = any(
                    abs(e["center_freq"] - inferred_freq) < 8
                    for e in registry
                )
                if not too_close:
                    registry.append(
                        {
                            "center_freq": inferred_freq,
                            "bandwidth": 15.0,
                            "hit_count": 0,
                            "first_seen_scan": None,
                            "last_seen_scan": None,
                            "is_wideband": True,
                            "inferred": True,
                        }
                    )

    # Also infer narrowband channels in guard gaps between confirmed widebands
    # Narrowbands sit at wideband_center + 12 (midpoint of guard gap)
    for slot in sorted(existing_slots):
        nb_freq = slot * grid + 7.5 + 12.0  # 7.5 + 12 = 19.5 for slot 0
        if 0 <= nb_freq <= 168:
            too_close = any(
                abs(e["center_freq"] - nb_freq) < 4
                for e in registry
                if not e.get("is_wideband", e["bandwidth"] >= 10)
            )
            if not too_close:
                # Check if we have any narrowband observations near this gap
                gap_obs = [
                    e
                    for e in registry
                    if not e.get("is_wideband", e["bandwidth"] >= 10)
                    and abs(e["center_freq"] - nb_freq) < 8
                ]
                if gap_obs:
                    # Already have observations here, skip inference
                    continue

    registry.sort(key=lambda e: e["center_freq"])
    return registry


@register_system("mubit_bsm")
class MubitBSMSystem(ContinualLearningSystem):
    """BSM-optimized system with structured transmitter registry.

    For BSM: maintains a running transmitter registry, merges peaks across
    scans, infers grid channels, and injects the full registry as structured
    context.

    For non-BSM tasks: delegates to the mubit_genai adapter (Mubit memory +
    native Google genai structured outputs).
    """

    supports_baseline = True
    parallel_safe = False  # Same as mubit_genai (google-genai fork issue)

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        top_k: int = 6,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ):
        self.model = model
        self.top_k = top_k
        self.user_system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature

        # BSM transmitter registry
        self._registry: list[dict] = []
        self._scan_count: int = 0

        # For non-BSM tasks: delegate to mubit_genai
        self._fallback: Optional[MubitGenAISystem] = None

        # Conversation context (within current instance)
        self.messages: list[dict[str, str]] = []
        self.interaction_count: int = 0
        self._last_query: Optional[Query] = None
        self._last_response: Optional[Response] = None
        self._at_instance_boundary: bool = True

        # genai client (for structured outputs)
        self._genai_client = None
        self._init_genai()

    def _init_genai(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set")
            return
        try:
            from google import genai  # type: ignore

            self._genai_client = genai.Client(api_key=api_key)
        except Exception:
            logger.error("Failed to init google-genai client", exc_info=True)

    def _get_fallback(self) -> "MubitGenAISystem":
        if self._fallback is None:
            from ..mubit_genai.system import MubitGenAISystem

            self._fallback = MubitGenAISystem(
                model=self.model,
                top_k=self.top_k,
                system_prompt=self.user_system_prompt,
                max_tokens=self.max_tokens,
            )
        return self._fallback

    # ---- ContinualLearningSystem interface ----

    def respond(self, query: Query) -> Response:
        prompt = query.prompt
        if _is_bsm(prompt):
            return self._respond_bsm(query)
        else:
            return self._get_fallback().respond(query)

    def observe(
        self, observation: Observation, next_query: Optional[Query] = None
    ) -> None:
        if self._last_query and _is_bsm(self._last_query.prompt):
            self._observe_bsm(observation)
        else:
            self._get_fallback().observe(observation, next_query)

    def reset(self) -> None:
        self._registry = []
        self._scan_count = 0
        self.messages = []
        self.interaction_count = 0
        self._last_query = None
        self._last_response = None
        self._at_instance_boundary = True
        if self._fallback:
            self._fallback.reset()

    @property
    def name(self) -> str:
        return "mubit_bsm"

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:
        return {
            "artifact_type": "mubit_bsm",
            "model": self.model,
            "registry_size": len(self._registry),
            "scan_count": self._scan_count,
        }

    # ---- BSM-specific logic ----

    def _respond_bsm(self, query: Query) -> Response:
        self.interaction_count += 1
        prompt = query.prompt

        # Extract peaks from the current scan
        peaks = _extract_peaks(prompt)
        self._scan_count += 1

        # Merge current peaks into the registry
        self._registry = _merge_into_registry(self._registry, peaks, self._scan_count)

        # Infer missing grid channels
        self._registry = _infer_grid_channels(self._registry)

        # Build the prompt with the registry injected
        registry_block = _format_registry(self._registry)
        registry_header = "=== ACCUMULATED TRANSMITTER REGISTRY ==="
        registry_footer = "========================================="

        # Extract just the scan data portion (skip the boilerplate)
        scan_data = self._extract_scan_data(prompt)

        full_prompt = (
            f"{registry_header}\n{registry_block}\n{registry_footer}\n\n"
            f"Current scan #{self._scan_count} peaks:\n{scan_data}\n\n"
            f"Report ALL transmitters from the registry (including inferred and "
            f"tentative ones). Also add any new peaks from the current scan that "
            f"aren't in the registry yet. Do NOT fragment a single transmitter "
            f"into multiple reports."
        )

        self._add_message("user", full_prompt)

        llm_messages = self.messages.copy()
        llm_messages.insert(0, {"role": "system", "content": BSM_SYSTEM_PROMPT})

        parsed, usage_event = self._genai_completion(
            BSM_SYSTEM_PROMPT, llm_messages, query.response_schema
        )

        if usage_event is not None:
            self.record_usage_event(usage_event)

        assistant_record = parsed.model_dump_json()
        self._add_message("assistant", assistant_record)

        response = Response(
            action=parsed,
            metadata={
                "interaction_count": self.interaction_count,
                "system_type": "mubit_bsm",
                "model": self.model,
                "registry_size": len(self._registry),
                "scan_peaks": len(peaks),
            },
        )
        self._last_query = query
        self._last_response = response
        return response

    def _observe_bsm(self, observation: Observation) -> None:
        instance_complete = observation_marks_instance_complete(observation)
        content = observation.content.strip()
        if content:
            self._add_message("user", f"FEEDBACK: {content}")
        if instance_complete:
            self.messages = []

    def _extract_scan_data(self, prompt: str) -> str:
        """Extract just the scan metadata and peaks from the full prompt."""
        lines = prompt.split("\n")
        scan_lines = []
        in_scan = False
        for line in lines:
            if "--- Scan" in line:
                in_scan = True
            if in_scan:
                scan_lines.append(line)
        return "\n".join(scan_lines) if scan_lines else prompt[-500:]

    def _add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def _genai_completion(
        self,
        system_content: str,
        contents_or_messages: list[dict],
        response_schema: type[BaseModel],
    ) -> tuple[BaseModel, Optional[UsageEvent]]:
        """Call google-genai with native response_schema structured output."""
        if self._genai_client is None:
            raise RuntimeError("google-genai client not initialized")

        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures._base import TimeoutError as FuturesTimeout
        import time as _time

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": self.temperature,
            "system_instruction": system_content,
        }
        if self.max_tokens:
            config["max_output_tokens"] = self.max_tokens

        # Convert messages to genai Content format
        genai_contents = []
        for msg in contents_or_messages:
            role = "model" if msg["role"] == "assistant" else "user"
            genai_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        max_retries = 6
        call_timeout = 120

        for attempt in range(max_retries):
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        self._genai_client.models.generate_content,
                        model=self.model,
                        contents=genai_contents,
                        config=config,
                    )
                    response = future.result(timeout=call_timeout)
                break
            except FuturesTimeout:
                logger.warning(
                    "genai call timed out (attempt %d/%d)", attempt + 1, max_retries
                )
                if attempt == max_retries - 1:
                    raise RuntimeError(f"genai timed out after {max_retries} attempts")
                _time.sleep(2 ** attempt)
            except Exception as exc:
                msg = str(exc)
                is_transient = any(
                    c in msg
                    for c in ("503", "429", "UNAVAILABLE", "500", "502", "504",
                              "timeout", "Connection", "deadlocked")
                )
                if not is_transient or attempt == max_retries - 1:
                    raise
                _time.sleep(2 ** attempt)

        parsed = response_schema.model_validate_json(response.text)

        usage_event = None
        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_t = getattr(usage, "prompt_token_count", None) or 0
            output_t = getattr(usage, "candidates_token_count", None) or 0
            usage_event = UsageEvent(
                call_type="completion",
                model=self.model,
                provider="google",
                input_tokens=input_t,
                output_tokens=output_t,
                total_tokens=getattr(usage, "total_token_count", None)
                or (input_t + output_t),
            )

        return parsed, usage_event
