"""LLM gateway (4.7): OpenAI-compatible, JSON-schema constrained,
budget-capped, with rule-engine fallback. Network calls are optional -
P0 tests run against a deterministic fake client.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """All retries exhausted / budget exhausted / invalid response."""


class ChatClient(Protocol):
    """OpenAI-compatible chat completion entry point."""

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> str:
        """Return the raw assistant message (expected JSON when schema given)."""
        ...


@dataclass
class CallRecord:
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost_cny: float


@dataclass
class LlmGateway:
    """Wraps a ChatClient with retries, schema validation and a budget.

    Budget policy (16.3): calls-per-run and CNY-per-run are hard caps;
    exhausting either raises E-LLM-BUDGET and the run escalates to human.
    """

    client: ChatClient
    model: str = "stub"
    max_calls_per_run: int = 60
    max_retries: int = 2
    cost_per_call_cny: float = 0.01
    budget_cny_per_run: float = 5.0
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def calls_used(self) -> int:
        return len(self.calls)

    @property
    def budget_used(self) -> float:
        return sum(record.cost_cny for record in self.calls)

    def chat(self, system: str, user: str, purpose: str,
             json_schema: dict | None = None) -> dict:
        """One constrained completion; invalid output retries, then the
        caller falls back to the rule engine (4.5)."""
        if self.calls_used >= self.max_calls_per_run:
            raise LLMError(
                f"budget: {self.max_calls_per_run} calls per run exhausted "
                f"(E-LLM-BUDGET) - escalate to human")
        if self.budget_used >= self.budget_cny_per_run:
            raise LLMError(
                f"budget: {self.budget_cny_per_run} CNY per run exhausted "
                f"(E-LLM-BUDGET) - escalate to human")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                raw = self.client.complete(system, user, json_schema)
                payload = json.loads(raw)
                if json_schema is not None:
                    import jsonschema

                    jsonschema.validate(payload, json_schema)
                self._record(purpose, start)
                return payload
            except json.JSONDecodeError as exc:
                last_error = exc      # invalid JSON: retry
            except Exception as exc:  # transport/schema: retry with backoff
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        raise LLMError(f"LLM failed after {self.max_retries + 1} attempts "
                       f"({last_error}) - fall back to rule engine")

    def _record(self, purpose: str, start: float) -> None:
        self.calls.append(CallRecord(
            model=self.model, purpose=purpose,
            prompt_tokens=0, completion_tokens=0,
            latency_ms=int((time.perf_counter() - start) * 1000),
            cost_cny=self.cost_per_call_cny))
