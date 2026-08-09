"""
Mubit memory system using Google's native genai SDK for structured outputs.

Same memory behavior as ``mubit`` (lesson storage + retrieval injection) but
uses the ``google-genai`` SDK directly with ``response_schema`` for guaranteed
structured outputs — bypassing LiteLLM's prompt-based text-parsing fallback
that the base harness uses for Gemini models (and which fails on long
rollouts). This makes gemini-3.5-flash viable for 120-hand poker runs.

Register as ``mubit_genai``. Use ``--system mubit_genai --system.model
gemini-3.5-flash``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from pydantic import BaseModel

from ...interface import Query, Response
from ...registry import register_system
from ...usage import UsageEvent
from ..mubit.system import DEFAULT_MODEL, MubitMemorySystem

logger = logging.getLogger(__name__)

# Default to gemini-3.5-flash for this system (the whole point is native
# structured outputs on a model that LiteLLM can't do structured output with).
DEFAULT_GENAI_MODEL = "gemini-3.5-flash"


@register_system("mubit_genai")
class MubitGenAISystem(MubitMemorySystem):
    """Mubit memory + native Google genai structured outputs."""

    # The google-genai HTTP client doesn't survive ProcessPoolExecutor forks
    # cleanly; force sequential execution so each system instance manages its
    # own client lifecycle without cross-process state issues.
    supports_baseline = True
    parallel_safe = False

    def __init__(
        self,
        model: str = DEFAULT_GENAI_MODEL,
        top_k: int = 6,
        system_prompt: str = "",
        max_tokens: Optional[int] = None,
        share_scope: str = "run",
        temperature: float = 0.0,
    ):
        # Override the default model BEFORE super().__init__ so the client and
        # metadata pick it up. We pass it explicitly to avoid the base default.
        super().__init__(
            model=model,
            top_k=top_k,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            share_scope=share_scope,
        )
        self.temperature = temperature
        self._genai_client = None
        self._init_genai()

    def _init_genai(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set; mubit_genai will fail on respond()")
            return
        try:
            from google import genai  # type: ignore

            self._genai_client = genai.Client(api_key=api_key)
        except Exception:
            logger.error("Failed to init google-genai client", exc_info=True)
            self._genai_client = None

    @property
    def name(self) -> str:
        return "mubit_genai"

    def get_run_artifacts(self) -> Optional[dict[str, Any]]:
        base = super().get_run_artifacts() or {}
        base["artifact_type"] = "mubit_genai"
        base["llm_backend"] = "google-genai-native"
        return base

    def respond(self, query: Query) -> Response:
        """Override to use google-genai SDK with response_schema."""
        self.interaction_count += 1

        retrieved = self._retrieve_lessons(query)
        query_content = self._inject_memory(query.prompt, retrieved)

        self._add_message("user", query_content)

        # Build the system prompt
        from ..mubit.system import RESPONSE_SYSTEM_PROMPT

        sys_parts = [RESPONSE_SYSTEM_PROMPT]
        if self.user_system_prompt:
            sys_parts.append(self.user_system_prompt)
        system_content = "\n\n".join(sys_parts)

        # Convert messages to genai Content format.
        # genai uses "user"/"model" roles; we map assistant->model.
        contents = []
        for msg in self.messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        parsed, usage_event = self._genai_completion(
            system_content, contents, query.response_schema
        )

        if usage_event is not None:
            self._note_prompt_token_usage(usage_event.input_tokens)
            self.record_usage_event(usage_event)

        assistant_record = parsed.model_dump_json()
        self._add_message("assistant", assistant_record)

        retrieved_texts = [r.get("text", "") for r in retrieved if r.get("text")]
        retrieved_meta = [
            {"id": r.get("id"), "text": r.get("text", ""), "metadata": r.get("metadata")}
            for r in retrieved
            if r.get("text")
        ]
        response = Response(
            action=parsed,
            metadata={
                "interaction_count": self.interaction_count,
                "system_type": "mubit_genai",
                "model": self.model,
                "llm_backend": "google-genai",
                "mubit_run_id": self._run_id,
                "retrieved_count": len(retrieved_texts),
                "retrieved_lessons": retrieved_texts[:6],
                "retrieved_lessons_meta": retrieved_meta[:6],
            },
        )
        self._last_query = query
        self._last_response = response
        return response

    def _genai_completion(
        self,
        system_content: str,
        contents: list[dict],
        response_schema: type[BaseModel],
    ) -> tuple[BaseModel, Optional[UsageEvent]]:
        """Call google-genai with native response_schema structured output."""
        if self._genai_client is None:
            raise RuntimeError("google-genai client not initialized (missing API key?)")

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            config["max_output_tokens"] = self.max_tokens

        # The system instruction goes in a separate config field.
        config["system_instruction"] = system_content

        # Retry on transient API errors (503 UNAVAILABLE, 429, timeouts, etc.).
        # The genai SDK can hang indefinitely on stalled HTTP connections, so
        # we wrap each call in a thread-based timeout.
        import time as _time
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures._base import TimeoutError as FuturesTimeout

        max_retries = 6
        call_timeout = 120  # seconds per API call

        for attempt in range(max_retries):
            try:
                # Run in a thread so we can enforce a hard timeout — the genai
                # SDK's HTTP client has no per-request timeout parameter.
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        self._genai_client.models.generate_content,
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    response = future.result(timeout=call_timeout)
                break
            except FuturesTimeout:
                logger.warning(
                    "genai call timed out after %ds (attempt %d/%d)",
                    call_timeout, attempt + 1, max_retries,
                )
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"genai call timed out after {call_timeout}s x {max_retries} attempts"
                    )
                _time.sleep(2 ** attempt)
            except Exception as exc:
                msg = str(exc)
                is_transient = any(
                    code in msg
                    for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "500", "502", "504",
                                 "timeout", "timed out", "Connection", "deadlocked")
                )
                if not is_transient or attempt == max_retries - 1:
                    raise
                wait = (2 ** attempt) * 1.0  # 1, 2, 4, 8, 16, 32s
                logger.warning(
                    "genai transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    wait,
                    msg[:120],
                )
                _time.sleep(wait)

        # Parse the structured JSON response.
        parsed = response_schema.model_validate_json(response.text)

        # Build UsageEvent from usage metadata.
        usage_event = None
        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_t = getattr(usage, "prompt_token_count", None) or 0
            output_t = getattr(usage, "candidates_token_count", None) or 0
            total_t = getattr(usage, "total_token_count", None) or (input_t + output_t)
            usage_event = UsageEvent(
                call_type="completion",
                model=self.model,
                provider="google",
                input_tokens=input_t,
                output_tokens=output_t,
                total_tokens=total_t,
            )

        return parsed, usage_event
