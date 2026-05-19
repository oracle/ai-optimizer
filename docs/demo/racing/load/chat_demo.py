"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Stress the chat path with N concurrent demo participants, each walking
through the racing-demo prompt sequence (LLM-only -> NL2SQL -> Vector
Search -> Combined -> Final Reveal). Each worker has a unique
``Client`` header so per-client settings, chat history, and the
ChatOrchestrator's session cache stay isolated.

The vector store must already be populated for steps 3 and 4 (see
``embed_per_document_table.py`` or ``embed_same_table.py``). If you run
the final step, run ``load_round6_team_points`` in the demo database
first so Round 6 team points exist. This script only exercises
``/v1/chat/completions`` and ``/v1/settings``.

Example:

    python chat_demo.py \\
        --api-key "$AIO_API_KEY" \\
        --base-url http://localhost:8000 \\
        --workers 100 \\
        --database-alias CORE \\
        --vs-alias-template 'RACING_PERDOC_DRIVER_{N:03d}' \\
        --steps 1,2,3,4,final

Notes on the server side:
  * Raise ``AIO_MAX_CLIENTS`` (default 64) above your --workers value so
    older clients are not LRU-evicted mid-run.
  * Configure an LLM in Configuration -> Models before running — each
    worker inherits whatever the CONFIGURED client has set.
  * Import ``prompts.json`` so NL2SQL / RAG prompts are racing-tuned.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from _chat_common import (  # noqa: E402
    StepPlan,
    WorkerResult,
    build_argparser,
    cfg_from_args,
    execute,
)

# ---------------------------------------------------------------------------
# Question banks (mirrors docs/demo/racing/demo_questions.md, condensed)
# ---------------------------------------------------------------------------


def _step1(n: int) -> list[str]:
    return [
        f"I am Driver {n}. What is my driving style?",
        f"I am Driver {n}. What team am I on?",
        f"I am Driver {n}. How many championship points do I have?",
        f"I am Driver {n}. What should I improve before the next race?",
    ]


def _step2(n: int, m: int) -> list[str]:
    return [
        f"I am Driver {n}. What is my driving style, vehicle setup, and team?",
        f"I am Driver {n}. How many points do I have before the finale?",
        f"I am Driver {n}. What was my best finish, and my fastest lap?",
        f"I am Driver {n}. Did I have any incidents? How many pit stops did I make?",
        (
            f"Compare Driver {n} with Driver {m} on total points, best finish, "
            "average lap time, and incidents."
        ),
        f"Which drivers have the same driving style as Driver {n}?",
        "Which team is leading before Round 6?",
    ]


def _step3(n: int) -> list[str]:
    return [
        f"I am Driver {n}. Summarize my driver briefing.",
        f"I am Driver {n}. What did my coach say I should improve?",
        f"I am Driver {n}. What setup advice was given to me?",
        f"I am Driver {n}. What does my race debrief say?",
        f"I am Driver {n}. What risks or weaknesses are mentioned in my notes?",
        f"I am Driver {n}. Give me three practical focus areas for my next simulator session.",
    ]


def _step4(n: int, m: int) -> list[str]:
    return [
        (
            f"I am Driver {n}. Use my database results and my documents to "
            "summarize my season so far."
        ),
        (
            f"I am Driver {n}. Based on my points, incidents, and coaching "
            "notes, what should I focus on next?"
        ),
        (
            f"I am Driver {n}. Which race should I review first, based on my "
            "worst structured result and my debrief notes?"
        ),
        (
            f"I am Driver {n}. Did my structured performance match the "
            "feedback in my documents?"
        ),
        (
            f"Compare Driver {n} with Driver {m} using both database results "
            "and driver notes."
        ),
    ]


def _final() -> list[str]:
    return [
        (
            "Using the database championship standings, which team won the "
            "championship? Show the pre-finale "
            "points, the Round 6 points, and the final total."
        ),
        (
            "Which teams were in contention before Round 6, and how did the "
            "final Round 6 database insert change the result?"
        ),
        "Show me when the Round 6 team points were recorded for each team.",
        "Show me the SQL used to calculate the final championship standings.",
    ]


# ---------------------------------------------------------------------------
# Step plan assembly
# ---------------------------------------------------------------------------


_STEP_DEFS = {
    "1": ("step1_llm_only", []),
    "2": ("step2_nl2sql", ["NL2SQL"]),
    "3": ("step3_vector", ["Vector Search"]),
    "4": ("step4_combined", ["Vector Search", "NL2SQL"]),
    "final": ("step_final_reveal", ["NL2SQL"]),
}


def _make_plan_builder(selected_steps: list[str]):
    def builder(
        n: int, m: int, vs_alias_for: Callable[[int], str]
    ) -> list[StepPlan]:
        out: list[StepPlan] = []
        for key in selected_steps:
            name, tools = _STEP_DEFS[key]
            if key == "1":
                qs = _step1(n)
            elif key == "2":
                qs = _step2(n, m)
            elif key == "3":
                qs = _step3(n)
            elif key == "4":
                qs = _step4(n, m)
            else:  # final
                qs = _final()
            out.append(
                StepPlan(
                    name=name,
                    tools_enabled=tools,
                    questions=qs,
                    vs_alias=vs_alias_for(n) if "Vector Search" in tools else None,
                )
            )
        return out

    return builder


def _parse_steps(raw: str) -> list[str]:
    parts = [s.strip().lower() for s in raw.split(",") if s.strip()]
    unknown = [p for p in parts if p not in _STEP_DEFS]
    if unknown:
        raise SystemExit(
            f"Unknown step(s) {unknown}. Valid steps: {sorted(_STEP_DEFS)}"
        )
    return parts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _partner_driver(n: int, rng: random.Random) -> int:
    # Any driver 1..100 distinct from N — only used for comparison-phrasing
    # in the question text, independent of --workers.
    while True:
        m = rng.randint(1, 100)
        if m != n:
            return m


def main() -> int:
    parser = build_argparser(__doc__)
    parser.add_argument(
        "--steps",
        default="1,2,3,4,final",
        help="Comma-separated step list. Choices: 1,2,3,4,final.",
    )
    parser.add_argument(
        "--vs-alias-template",
        default="RACING_PERDOC_DRIVER_{N:03d}",
        help=(
            "Python format string for the per-driver vector store alias. "
            "{N} (or {N:03d}) is the driver number. Use a constant string "
            "(e.g. 'RACING_SHARED') if every driver shares one alias."
        ),
    )
    parser.add_argument(
        "--driver-offset",
        type=int,
        default=0,
        help=(
            "Offset added to worker_id when computing driver number. "
            "Driver number = (worker_id + offset) %% 100 + 1."
        ),
    )
    parser.add_argument(
        "--partner-seed",
        type=int,
        default=42,
        help="Seed for the random partner-driver picker (for stable runs).",
    )
    args = parser.parse_args()

    selected_steps = _parse_steps(args.steps)
    cfg = cfg_from_args(args)

    rng = random.Random(args.partner_seed)
    results = []
    for i in range(cfg.workers):
        n = (i + args.driver_offset) % 100 + 1
        m = _partner_driver(n, rng)
        results.append(
            WorkerResult(
                worker_id=i,
                client_id=f"{cfg.client_prefix}{i:03d}",
                driver_n=n,
                driver_m=m,
            )
        )

    def vs_alias_for(n: int) -> str:
        return args.vs_alias_template.format(N=n, n=n)

    print(
        f"Running {cfg.workers} workers, steps={selected_steps}, "
        f"vs_alias_template={args.vs_alias_template!r}, "
        f"database_alias={cfg.database_alias!r}"
    )
    return execute(cfg, results, _make_plan_builder(selected_steps), vs_alias_for)


if __name__ == "__main__":
    sys.exit(main())
