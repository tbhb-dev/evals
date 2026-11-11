---
type: Eval
id: _/E-000001
title: Which agent harness does the best web research
state: designed
generated:
  - role: generated
    harness: claude-code:2.1.322
    model: anthropic:claude-opus-5-5
    effort: medium
    surface: cli
    session: sha-256-64:6ed5a3a4b9558ce5
    at: "2026-11-11T18:18:56Z"
---

# Which agent harness does the best web research

## Question

Given the same research question and instructions, which harness returns the most accurate, best-cited and most current answer with the fewest fabrications? The candidates are Codex, Claude Code, Claude Code running its deep-research skill, and Antigravity. tbhb-dev uses the result to choose a default harness for research briefs and reviews, and to choose whether briefs should route by question type.

## Systems under test

Each harness runs its own current flagship model at high effort. `claude-dr` is a workflow rather than a harness: the deep-research skill has Claude Code coordinate research subagents and a report-writing subagent, so it enters as a system of its own beside plain Claude Code. The question concerns each harness in its released form, so the design doesn't try to separate the model from the harness. Versions go into each run record.

| Label | Harness | Model | Effort |
| --- | --- | --- | --- |
| `codex` | `Codex CLI` | gpt-6.1-sol | high |
| `claude` | Claude Code | claude-opus-5-5 | high |
| `claude-dr` | Claude Code with its deep-research skill | claude-opus-5-5 | high |
| `agy` | `Antigravity CLI` | gemini-4-argon-high | none (the model ID includes the effort) |

## Task set

In the full set, 32 questions fall into five strata. Each question has a short canonical answer, the primary source that establishes it, the date someone verified it, and a grading note.

| Stratum | Count | What it tests |
| --- | --- | --- |
| Stable | 6 | Settled facts that training data likely covers |
| Recent | 8 | Facts that changed in the weeks before the run |
| Niche | 8 | Answers found only in changelogs, standards, and small project docs |
| Multi-hop | 5 | Answers that need two or three sources |
| False premise | 5 | Questions whose right answer is "no such thing" or "not public" |

A pilot of 8 questions came first, with every question run three times per harness for 72 scored runs. Every system answered nearly every pilot question correctly, so the pilot couldn't separate them. The full run uses 32 new questions, each run three times per system, which comes to 384 scored runs with all four systems.

One drafter writes each candidate and a different one answers it. Half the candidates come from a Claude drafter and half from a Codex drafter, so the set isn't shaped by what one harness finds easy. By hand, the coordinator verifies every candidate against its primary source and drops anything ambiguous. Each recent-stratum answer is valid only for the run window, and each phase runs inside 72 hours so answers can't drift.

The coordinator builds the full set to be harder. Each question meets at least one of these criteria:

- The answer appears only in a changelog, an issue tracker, or the text of a standard, not in a summary.
- It takes two or three sources and a computed or joined answer.
- It concerns a fact from the 14 days before the run.
- It rests on a false premise that sits close to a real fact.
- It needs an exact version or date.

The coordinator never keeps or drops a question because of how a system under test answered it.

This repository contains the design and the method for now. Questions, key, and per-question results come after grading. Systems under test could search a public key, so [PROTOCOL.md](../../../PROTOCOL.md) says to hold it back until the last run.

## Method

- All systems receive the same brief from one template. The brief poses the question and tells the system to research it on the live web with its own search and fetch tools. Network access from the shell and file edits are off limits, and the brief doesn't list sources.
- The system answers through a fixed JSON schema with an answer and a confidence of high, medium, or low. It adds a premise flag, claims with citations (URL plus a verbatim quote), and the tools it used.
- Each run is a fresh session with no memory of earlier runs.
- The run order changes at random each round, where a round is one pass over every question and harness pair. That spreads time-of-day and quota effects evenly.
- A run that times out counts as a scored failure. A run lost to infrastructure, such as a dropped connection or a quota error before the first model turn, gets one rerun. The record keeps and flags both runs.
- Each run records harness, model, effort, version, task-set commit, start and end times, and exit status. It also records tokens for every run, and cost where the harness reports it.
- Each run records a tool-call trace taken from the harness's own event stream, not from the answer's self-reported tool list. A call outside a system's launch profile stops that system's remaining runs.
- `claude-dr` gets the same brief, with its file rules adjusted: it may write research notes and its report only inside its working directory, and it may not ask follow-up questions. It answers through the same schema, built from its own report. The judges see only that blinded answer, and the narrative report stays in the record without a grade.
- A system whose launch profile gives it file tools runs inside an operating-system sandbox, and the report says what confined it. Antigravity takes part only if its own sandbox passes a test against dummy files. If the test fails, Antigravity stays out, and the report says why.

### Capability check

Before any scored run, each harness answers canary questions whose answers exist only on pages newer than every model's training cutoff. That proves it can search and fetch live pages as launched. The check also sizes wall time per run. It isn't scored.

The check ran twice. In round one, Codex could only use cached search and couldn't verify the canary. Because Antigravity had one search tool, it said with high confidence that a repository existed nowhere, which was wrong. Claude hit a usage limit. After Codex got live search and the quota reset, round two passed: all six runs on two fresh facts answered correctly with live search or fetch.

## Grading

Grading is blind and has four steps.

1. **Normalize.** A script extracts each run's JSON and drops tool traces and run metadata. It also scrubs model and harness names from answer text and assigns a random label. Nobody opens the label map until scores are final.
2. **Check citations.** A script fetches every cited URL with a guard against requests to private network addresses. It records status, final URL, and whether the quoted text appears on the page.
3. **Judge.** The judges, one running claude-opus-5-5 and one running gpt-6.1-sol, score each answer against the key. Neither sees the label map. Antigravity doesn't judge. Because two of the three harness families judge, the report compares each judge's scores for its own family against the other judge's. The Claude judge shares a family with both `claude` and `claude-dr`, so each of the two gets its own comparison.
4. **Resolve.** Disagreements of more than one rubric point go to the coordinator, who checks the source. The coordinator also spot-checks 10% of agreed items.

| Criterion | Scale |
| --- | --- |
| Accuracy | 0 wrong, 1 partial, 2 correct. For false-premise questions, 2 means the system rejected the premise. |
| Citation quality | 0 to 3, by the share of claims with a live citation whose quote appears on the page and supports the claim |
| Recency | Recent stratum only. 2 is current, 1 is stale but dated, 0 is stale and presented as current. |
| Hallucinations | Count of fabricated URLs, quotes missing from the page, and false claims stated as fact, reported per run and per citation so that a longer answer isn't penalized for length alone |
| Calibration | Derived Brier score, with high, medium, and low mapped to 0.9, 0.6, and 0.3 |
| Time and cost | Wall-clock seconds and any tokens or cost the harness reports |

## Analysis

The analysis draws bootstrap samples of questions, not runs, to get 95% intervals for each harness and stratum. It compares harnesses pairwise with a paired sign-flip test over questions. With this many questions, differences under roughly 10 points of accuracy aren't distinguishable, and the report says so instead of ranking on noise. See [tools/README.md](tools/README.md) for the citation checker, analysis, and blinding tools.

## Costs and bounds

- **Paid turns.** The pilot needed 72 scored runs and about 150 judge passes. The full run needs up to 384 scored runs and about 770 judge passes. Everything runs on the subscription logins the harnesses already use, with no API keys. The whole full run may use about a quarter of a week's Claude usage. The coordinator reads usage before and after the capability check.
- **Time.** Each phase finishes inside 72 hours. Each run has a 15-minute limit. `claude-dr` gets a limit set from its capability-check times, at no more than 30 minutes.
- **Stop rules.** Stop and report if a harness has no web access, if a quota runs out mid-round, or if more than 10% of runs fail for infrastructure reasons.

## Status

The pilot ran, and two judges graded it. Its eight questions put every system at or near full accuracy. The full run adds harder questions, `claude-dr`, token and cost records, and independent tool traces. Antigravity joins only if its sandbox passes a test. The full run's design is final, and its runs haven't started.
