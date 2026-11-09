---
type: Eval
id: _/E-000001
title: Which agent harness does the best web research
state: designed
generated:
  - role: generated
    harness: claude-code:2.1.319
    model: anthropic:claude-sonnet-5-5
    effort: medium
    surface: cli
    session: sha-256-64:6ed5a3a4b9558ce5
    at: "2026-11-09T04:53:59Z"
---

# Which agent harness does the best web research

## Question

Given the same research question and instructions, which harness returns the most accurate, best-cited and most current answer with the fewest fabrications? The candidates are Codex, Claude Code, and Antigravity. tbhb-dev uses the result to choose a default harness for research briefs and to choose whether briefs should route by question type.

## Systems under test

Each harness runs its own current flagship model at high effort. The question concerns each harness in its released form, so the design doesn't try to separate the model from the harness. Versions go into each run record.

| Label | Harness | Model | Effort |
| --- | --- | --- | --- |
| `codex` | `Codex CLI` | gpt-6.1-sol | high |
| `claude` | Claude Code | claude-opus-5-5 | high |
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

A pilot of 8 questions comes first. Every pilot question runs three times per harness, for 72 scored runs. Spending on the full 32 by 3 run waits for the pilot.

One drafter writes each candidate and a different one answers it. Half the candidates come from a Claude drafter and half from a Codex drafter, so the set isn't shaped by what one harness finds easy. By hand, the coordinator verifies every candidate against its primary source and drops anything ambiguous. Each recent-stratum answer is valid only for the run window, and the whole pilot runs inside 72 hours so answers can't drift.

This repository contains the design and the method for now. Questions, key, and per-question results come after grading. Systems under test could search a public key, so [PROTOCOL.md](../../../PROTOCOL.md) says to hold it back until the last run.

## Method

- All systems receive the same brief from one template. The brief poses the question and tells the system to research it on the live web with its own search and fetch tools. Network access from the shell and file edits are off limits, and the brief doesn't list sources.
- The system answers through a fixed JSON schema with an answer and a confidence of high, medium, or low. It adds a premise flag, claims with citations (URL plus a verbatim quote), and the tools it used.
- Each run is a fresh session with no memory of earlier runs.
- The run order changes at random each round, where a round is one pass over every question and harness pair. That spreads time-of-day and quota effects evenly.
- A run that times out counts as a scored failure. A run lost to infrastructure, such as a dropped connection or a quota error before the first model turn, gets one rerun. The record keeps and flags both runs.
- Each run records harness, model, effort, version, task-set commit, start and end times, exit status, and tokens or cost where the harness reports them.

### Capability check

Before any scored run, each harness answers canary questions whose answers exist only on pages newer than every model's training cutoff. That proves it can search and fetch live pages as launched. The check also sizes wall time per run. It isn't scored.

The check ran twice. In round one, Codex could only use cached search and couldn't verify the canary. Because Antigravity had one search tool, it said with high confidence that a repository existed nowhere, which was wrong. Claude hit a usage limit. After Codex got live search and the quota reset, round two passed: all six runs on two fresh facts answered correctly with live search or fetch.

## Grading

Grading is blind and has four steps.

1. **Normalize.** A script extracts each run's JSON and drops tool traces and run metadata. It also scrubs model and harness names from answer text and assigns a random label. Nobody opens the label map until scores are final.
2. **Check citations.** A script fetches every cited URL with a guard against requests to private network addresses. It records status, final URL, and whether the quoted text appears on the page.
3. **Judge.** The judges, one running claude-opus-5-5 and one running gpt-6.1-sol, score each answer against the key. Neither sees the label map. Antigravity doesn't judge. Because two of the three harness families judge, the report compares each judge's scores for its own family against the other judge's.
4. **Resolve.** Disagreements of more than one rubric point go to the coordinator, who checks the source. The coordinator also spot-checks 10% of agreed items.

| Criterion | Scale |
| --- | --- |
| Accuracy | 0 wrong, 1 partial, 2 correct. For false-premise questions, 2 means the system rejected the premise. |
| Citation quality | 0 to 3, by the share of claims with a live citation whose quote appears on the page and supports the claim |
| Recency | Recent stratum only. 2 is current, 1 is stale but dated, 0 is stale and presented as current. |
| Hallucinations | Count of fabricated URLs, quotes missing from the page, and false claims stated as fact |
| Calibration | Derived Brier score, with high, medium, and low mapped to 0.9, 0.6, and 0.3 |
| Time and cost | Wall-clock seconds and any tokens or cost the harness reports |

## Analysis

The analysis draws bootstrap samples of questions, not runs, to get 95% intervals for each harness and stratum. It compares harnesses pairwise with a paired sign-flip test over questions. With this many questions, differences under roughly 10 points of accuracy aren't distinguishable, and the report says so instead of ranking on noise. See [tools/README.md](tools/README.md) for the citation checker, analysis, and blinding tools.

## Costs and bounds

- **Paid turns.** The pilot needs 72 scored runs and about 150 judge passes. The full set would need 288 scored runs and about 600 judge passes. Everything runs on the subscription logins the harnesses already use, with no API keys.
- **Time.** The pilot finishes inside 72 hours. Each run has a 15-minute limit.
- **Stop rules.** Stop and report if a harness has no web access, if a quota runs out mid-round, or if more than 10% of runs fail for infrastructure reasons.

## Status

The design is final, and tbhb chose the high effort, the two blind judges, and the pilot-first scale. The capability check passed in round two. Grading tools for citations, analysis, and blinding have merged and passed their tests. The pilot hasn't started.
