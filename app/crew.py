"""Report-writing crew (CrewAI): an Insight Analyst finds the story in the numbers,
a Report Writer turns it into a short executive report. Runs as one node of the LangGraph.

Falls back to a single LLM call when CrewAI is disabled or a FakeLLM is in use (tests)."""
from __future__ import annotations

import time

from .config import settings
from .llm import LLM, CallUsage, FakeLLM, temperature_kwargs

GROUNDING_RULE = (
    "Cite ONLY figures that appear in the RESULTS or STATS, copied exactly as shown, "
    "including the leading minus sign and the same decimal places. "
    "A value shown as -10.87 must be written -10.87, never 10.87 or 10.87%. "
    "Do not append a percent sign unless that character is already part of the printed figure. "
    "Never estimate, extrapolate, or invent a number, and do not calculate a new difference, "
    "growth percent, combined share, or ratio in the prose. If that comparison is not already "
    "printed in RESULTS or STATS, describe it in words with no number "
    "(for example: \"Punjab is well ahead of Sindh\"). "
    "If the results do not contain the year, metric, or identifier the question asks about, "
    "say that the data does not contain it. Do not describe a zero-filled gap as a real comparison."
)


def _context_block(ctx: dict) -> str:
    return (
        f"QUESTION: {ctx['question']}\n\nPLAN:\n{ctx['plan']}\n\nSQL:\n{ctx['sql']}\n\n"
        f"RESULTS ({ctx['row_count']} rows, first rows shown):\n{ctx['result_preview']}\n\n"
        f"STATS (computed in sandbox):\n{ctx['stats']}\n"
        + (f"\nPREVIOUS DRAFT WAS REJECTED BY A VALIDATOR:\n{ctx['feedback']}\nFix this.\n" if ctx.get("feedback") else "")
    )


def write_report(ctx: dict, llm: LLM) -> str:
    if isinstance(llm, FakeLLM) or not settings.use_crewai:
        system = f"You are a senior data analyst writing a concise markdown report. {GROUNDING_RULE}"
        started = time.perf_counter()
        text = llm.complete("report", system, _context_block(ctx), ctx)
        write_report.last_split = {"llm_ms": int((time.perf_counter() - started) * 1000)}
        return text
    text, usage, split = _crew_report(ctx)
    write_report.last_split = split
    if hasattr(llm, "last_usage"):
        llm.last_usage = usage
    return text


def analyst_task_text() -> str:
    return (
        "Read the context and list the key findings as bullet points, each with the exact "
        f"supporting number. {GROUNDING_RULE}"
    )


def writer_task_text() -> str:
    return (
        "Using the analyst's findings, write the final report: '## Answer' (1-2 sentences "
        "directly answering the question), '## Key findings' (bullets), '## Caveats' "
        f"(data limits, 1-3 bullets). {GROUNDING_RULE}"
    )


def _crew_usage(result: object, crew: object) -> CallUsage:
    """Token totals from the crew run. Cost is priced from those counts."""
    usage = getattr(result, "token_usage", None) or getattr(crew, "usage_metrics", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
    cost = 0.0
    if prompt or completion:
        try:
            import litellm
            cost = float(litellm.completion_cost(
                model=settings.llm_model, prompt_tokens=prompt, completion_tokens=completion,
            ))
        except Exception:
            cost = 0.0
    return CallUsage(tokens=total, cost_usd=cost)


def _crew_report(ctx: dict) -> tuple[str, CallUsage, dict]:
    from crewai import LLM as CrewLLM, Agent, Crew, Process, Task

    model = CrewLLM(model=settings.llm_model, **temperature_kwargs())

    analyst = Agent(
        role="Insight Analyst",
        goal="Find the 3-5 findings in the query results that best answer the business question.",
        backstory="A sceptical analyst who never states a number that isn't in the data.",
        llm=model, allow_delegation=False, verbose=False,
    )
    writer = Agent(
        role="Report Writer",
        goal="Write a short, decision-ready markdown report for a non-technical manager.",
        backstory="Writes plain-English reports that lead with the answer.",
        llm=model, allow_delegation=False, verbose=False,
    )

    find = Task(
        description=analyst_task_text() + "\n\n{context}",
        expected_output="3-5 bullet findings, each citing exact numbers from the results.",
        agent=analyst,
    )
    write = Task(
        description=writer_task_text(),
        expected_output="A markdown report under 250 words with the three sections.",
        agent=writer,
        context=[find],
    )

    marks = [time.perf_counter()]

    def _mark(_output) -> None:
        marks.append(time.perf_counter())

    crew = Crew(
        agents=[analyst, writer], tasks=[find, write], process=Process.sequential,
        verbose=False, task_callback=_mark,
    )
    result = crew.kickoff(inputs={"context": _context_block(ctx)})
    split: dict[str, int] = {}
    if len(marks) >= 3:
        split["analyst_ms"] = int((marks[1] - marks[0]) * 1000)
        split["writer_ms"] = int((marks[2] - marks[1]) * 1000)
    return str(result.raw).strip(), _crew_usage(result, crew), split
