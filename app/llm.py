"""LLM access. One provider-agnostic interface (litellm) + a scripted fake for tests/offline demos."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .config import settings


@dataclass
class CallUsage:
    """Tokens and USD cost of the most recent model call. FakeLLM stays at zero."""

    tokens: int = 0
    cost_usd: float = 0.0


class LLM(Protocol):
    def complete(self, role: str, system: str, user: str, ctx: dict) -> str: ...


def temperature_kwargs(raw: str | None = None) -> dict[str, float]:
    """Sampling kwargs from LLM_TEMPERATURE.

    Empty omits the parameter. A number is sent as that value.
    """
    text = (settings.llm_temperature if raw is None else raw).strip()
    if not text:
        return {}
    return {"temperature": float(text)}


class LiteLLM:
    """Real model via litellm (same router CrewAI uses under the hood)."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.llm_model
        self.last_usage = CallUsage()

    def complete(self, role: str, system: str, user: str, ctx: dict) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **temperature_kwargs(),
        )
        usage = getattr(resp, "usage", None)
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        try:
            cost = float(litellm.completion_cost(completion_response=resp))
        except Exception:
            cost = 0.0
        self.last_usage = CallUsage(tokens=total, cost_usd=cost)
        return resp.choices[0].message.content or ""


Response = str | Callable[[dict], str]


class FakeLLM:
    """Deterministic stand-in. `script` maps role -> list of responses, consumed in order.
    The last response for a role repeats. A response may be a callable taking ctx."""

    def __init__(self, script: dict[str, list[Response]], delay_s: float = 0.0):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, str]] = []
        self.systems: list[tuple[str, str]] = []  # (role, system prompt), for prompt tests
        self.delay_s = delay_s  # simulate model latency (offline demos, streaming UI tests)
        self.last_usage = CallUsage()

    def complete(self, role: str, system: str, user: str, ctx: dict) -> str:
        self.calls.append((role, user))
        self.systems.append((role, system))
        if self.delay_s:
            time.sleep(self.delay_s)
        queue = self.script.get(role)
        if not queue:
            raise KeyError(f"FakeLLM has no script for role '{role}'")
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        return resp(ctx) if callable(resp) else resp


def demo_llm() -> FakeLLM:
    """Offline demo: previews the first table and reports row count. No API key needed."""

    def sql(ctx: dict) -> str:
        return f"SELECT * FROM {ctx['tables'][0]} LIMIT 20"

    def report(ctx: dict) -> str:
        return (
            f"## Summary\nThe query returned {ctx['row_count']} rows from "
            f"`{ctx['tables'][0]}`.\n\n(Offline demo mode: set LLM_MODE=live for real analysis.)"
        )

    return FakeLLM(delay_s=settings.demo_delay_s, script={
        "planner": ["1. Preview the data.\n2. Summarise it."],
        "sql": [sql],
        "analysis_code": ["import json\nprint(json.dumps({'rows': len(df)}))"],
        "report": [report],
    })


def get_llm() -> LLM:
    return demo_llm() if settings.llm_mode == "fake" else LiteLLM()


_WRAPPED = re.compile(r"```(?:[a-zA-Z]+)?[ \t]*\r?\n(.*)\r?\n?```[ \t]*", re.S)
_OPEN_LINE = re.compile(r"^```(?:[a-zA-Z]+)?[ \t]*\r?\n")
_CLOSE_LINE = re.compile(r"\r?\n?```[ \t]*$")


def strip_fences(text: str) -> str:
    """Pull code out of a ```lang fence if the model wrapped it.

    A matched pair is unwrapped. A lone opening line and/or a lone trailing
    fence is removed too. Backticks that are part of the query stay put.
    """
    text = text.strip()
    wrapped = _WRAPPED.fullmatch(text)
    if wrapped:
        return wrapped.group(1).strip()
    text = _OPEN_LINE.sub("", text, count=1)
    text = _CLOSE_LINE.sub("", text, count=1)
    return text.strip()
