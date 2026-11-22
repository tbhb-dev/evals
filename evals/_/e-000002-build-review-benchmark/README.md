---
type: Eval
id: _/E-000002
title: Build and review benchmark
state: designed
generated:
  - role: generated
    harness: claude-code:2.1.322
    model: anthropic:claude-opus-5-5
    effort: medium
    surface: cli
    session: sha-256-64:6ed5a3a4b9558ce5
    subagent: sha-256-64:c8be8bd8f8b0bf36
    at: "2026-11-22T09:40:46Z"
  - role: assisted
    harness: claude-code:2.1.322
    model: anthropic:claude-sonnet-5-5
    effort: medium
    surface: cli
    session: sha-256-64:6ed5a3a4b9558ce5
    at: "2026-11-22T09:40:46Z"
---

# Build and review benchmark

## Question

How well does each model build a change to a brief, and how well does it review someone else's change? tbhb-dev runs this suite on each new model and uses the result to update its model roster. A passing gate hides much of what separates builders and reviewers, such as summaries that misstate size, work beyond the brief, or reviews that miss a real hole.

The suite has five task kinds: build, review, ops, administration, and design. Version 1 covers build and review over 5 tasks. Design follows in version 2, and ops and administration in version 3.

## Systems under test

Each row measures a model inside its harness under one launch profile. Versions go into each run record.

| Kind | Harness | Model |
| --- | --- | --- |
| Build | `Codex CLI` | `gpt-6.1-sol` |
| Build | Claude Code | `claude-sonnet-5-5` |
| Build | `Antigravity CLI` (`agy`) | `gemini-4-argon-high` |
| Review | `Codex CLI` | `gpt-6.1-sol` |
| Review | Claude Code | `claude-opus-5-5` |
| Review | `Antigravity CLI` (`agy`) | `gemini-4-argon-high` |

## Task set

Each task comes from a real merged pull request in a tbhb-dev repository. One task yields a build brief and a review fixture, from the same pull request or from the one whose defect it repaired. A task enters a suite version only after scorer runs show its visible gate or a hidden check failing on the parent commit, and both passing on the merge.

Tasks stay in the private half while they're active. Snapshots, briefs, gates, hidden checks, and defect keys go there, and this repository has only the format below. A retired task from a public repository may move here after the coordinator reviews the move, while a task from a private repository never does.

### Layout

```text
evals/_/e-000002-build-review-benchmark/
  suite/v<N>.json              task IDs with revisions, systems, repeats, judge table
  tasks/<task-id>/
    task.json                  ID, revision, kinds, limits, gate, paths, tags, status
    provenance.json            source repository, pull request, commits, dates, owner, visibility
    brief.md                   what the model under test reads, nothing more
    snapshot.bundle            git bundle of the parent commit, one branch, no remote
    gate.sh                    visible gate, shipped with the run
    hidden/                    never shipped: extra tests, checks, expected end state
    rubric.json                must and must-not items for judges, with weights
    reference.patch            the merged change, for the fail-before check and as a hint to judges
    review/<fixture-id>/
      head.bundle              the head under review, on top of the snapshot
      pr.md                    the pull request text the reviewer sees
      key.json                 defects with class, location, root cause, and source
```

### `task.json`

```json
{
  "id": "t-0001-example",
  "revision": 1,
  "kinds": ["build", "review"],
  "status": "active",
  "canary": "<random 128-bit hex>",
  "limits": {"wall_seconds": 3600, "changed_lines": 400},
  "allowed_paths": ["src/example/**"],
  "generated": [{"path": "<exact lockfile path>", "regenerate": "<command that rebuilds it>"}],
  "gate": {"cmd": "./gate.sh", "wall_seconds": 1200, "needs": ["bazel", "network"]},
  "hidden": {"cmd": "hidden/check.sh", "wall_seconds": 1200},
  "tags": ["security"],
  "fail_before": {"run": "<run-id>", "result": "fail"},
  "pass_after": {"run": "<run-id>", "result": "pass"}
}
```

Only the task file contains the canary string, and a model's output or public text that contains it shows a leak. Each `generated` entry names one exact path, never a glob, with the command that reproduces it.

### `provenance.json`

```json
{
  "repository": "<owner>/<repo>",
  "visibility": "public | private",
  "pr": 0,
  "merge_commit": "<sha>",
  "parent_commit": "<sha>",
  "merged_at": "<UTC timestamp>",
  "squashed": true,
  "builder_head": "<sha or null>",
  "owner_role": "<repository's owning role>",
  "brief_source": "pr-body | reconstructed | private-prefix-plus-body",
  "redactions": ["<what was paraphrased or removed>"],
  "key_signed_by": "<owning role>",
  "caveats": ["<from the owner>"]
}
```

A squashed merge can hold the owner's follow-ups, and then the reference diff isn't the builder's work alone. The `squashed` and `builder_head` fields record that.

### Review `key.json`

```json
{
  "fixture": "f-0001a-builder-head",
  "kind": "historical | seeded | control | build-output",
  "debt_cap": 3,
  "defects": [
    {"id": "d1", "class": "BLOCK", "file": "src/example/handler.go",
     "lines": [40, 58], "root_cause": "<one line>",
     "source": "<review or owner read that found it>", "security": true}
  ]
}
```

A historical fixture is the builder's head before review, keyed with the defects that later reviews or the owner found. Seeded fixtures add one to three defects to a clean merge. A control's empty `defects` list says nobody knows of a defect, and it proves nothing more.

### Run outputs

| Kind | File | Contents |
| --- | --- | --- |
| Build | `SUMMARY.json` | Claimed files, lines added and removed, gate result, what it didn't do, and any deviation from the brief |
| Build | the clone | Working tree and any local commits, bundled by the runner after exit |
| Review | `REVIEW.json` | Verdict `approve` or `changes`, and findings with file, line, class, title, and rationale |

### Versions

Task IDs never change or return, and any edit to a task's brief, gate, hidden checks, rubric, or key raises its revision. Each suite version freezes task revisions, systems, repeats, and the judge table, and scores compare only within one version. Each new version retires about a quarter of the active tasks, oldest merge first, and the current roster models rerun on it.

## Method

The runner extends the `_/E-000001` launcher. Each run starts in a `bwrap` jail on a Linux host, with a private home and only its own harness's subscription login, and the jail hides other runs and logins as a measurement control.

- A build run gets the brief, the snapshot, and the visible gate. It never sees the hidden checks or the reference diff, and it may commit locally.
- A review run gets the base snapshot, the head, and the pull request text, and it writes `REVIEW.json`.
- Runs can't push. The clone has no remote, and the launcher refuses to start when its environment contains a GitHub or Secure Shell (SSH) credential or a 1Password token.
- After a run ends, a separate jailed scorer without a model applies the run's clone to a fresh snapshot. Then it runs the gate and the hidden checks and measures the diff, which keeps the run from scoring itself.
- A trace scan marks a run `contaminated` when it fetched the task's source repository, pull request, or merge commit. Such runs count in a separate column, outside the headline.
- A refusal is the result. Nobody reruns a refused task on another provider or with a reworded brief.

Each system runs each task 3 times, in a shuffled order each round. Failed, timed-out, refused, and stopped runs all count as results.

## Grading

Scripts score what they can. The standing judges, `claude-opus-5-5` and `gpt-6.1-sol`, grade the rest blind and without tools, and neither grades its own model's output. A fixed table in the runner picks them, so no maker picks its reviewer.

| Output from | Standing judges that count | Provisional |
| --- | --- | --- |
| Codex `gpt-6.1-sol` | `claude-opus-5-5` | `agy` |
| Claude `claude-sonnet-5-5` | `gpt-6.1-sol` and `claude-opus-5-5`, the second reported apart | none |
| Claude `claude-opus-5-5` | `gpt-6.1-sol` | `agy` |
| `agy` `gemini-4-argon-high` | `claude-opus-5-5` and `gpt-6.1-sol` | none |

Where only one standing judge counts, a judged `BLOCK` or match stands only after the repository's owner confirms it. Provisional `agy` grades go to a separate file and count only after `agy` passes a calibration whose pass rule the `evals` role fixes first.

### Builds

A build is merge-ready when the gate and hidden checks pass, the size fits the limit, and every changed file is under the allowed paths. The judges must also find every rubric item met, and the run can't have a confirmed `BLOCK` or a summary that misstates the gate result. The merge-ready rate is the headline.

| Measure | How | Label |
| --- | --- | --- |
| Gate, hidden checks | exit status in the scorer's jail | measured |
| Size | changed lines from `git diff --numstat`, minus generated files the scorer reproduces byte for byte | measured |
| Scope | files outside `allowed_paths` | measured |
| Summary honesty | claimed against measured lines, files, and gate result, plus omissions the judges find | measured and inferred |
| Brief adherence, rework | rubric items met, and findings classed `BLOCK`, `TECH-DEBT`, or `SECURITY-DEBT` | inferred |
| Cost | wall seconds and tool calls, plus tokens where the harness reports them | measured or reported |

### Reviews

A script pairs each finding with key defects in the same file within 10 lines, and the judges rule on each pair. Matching is one-to-one. The repository's owner rules on each unmatched `BLOCK` as real and new, false, or debatable, and real new findings join the key in the task's next revision.

| Measure | How | Label |
| --- | --- | --- |
| Severe recall | `BLOCK` and `SECURITY-DEBT` key defects matched at a severe enough class, the headline | inferred |
| Recall | all key defects matched at the class each needs | inferred |
| Precision | matched findings over matched plus false ones, with unmatched debt findings past `debt_cap` counted false unless ruled real | inferred |
| False blocks | unmatched `BLOCK` findings ruled false, per fixture, with controls apart | inferred, by adjudication |
| Severity agreement | finding class against key class on matched pairs | measured |
| Refusal rate | runs that end in a refusal | measured |

### Analysis

The task is the unit of analysis, and intervals come from bootstrap samples over tasks. Separating two models by 15 points at 80% power needs about 43 tasks per kind, under an assumed 0.35 standard deviation that version 1 measures. Version 1's 5 tasks rank nothing and report per-task results.

## Costs and bounds

- **Version 1 runs.** 45 build runs and 54 review runs, plus 6 run canaries and 1 judge canary that nobody scores. Builds get 3,600 seconds plus a 1,200-second gate, and reviews get 1,800 seconds.
- **Quota.** Runs use subscription logins, never an API key. Claude-quota runs and judge passes may use at most 20% of the seven-day Claude limit from the suite's baseline reading, and never pass a 0.60 reading.
- **Launch gate.** One gate covers runs and judge calls, and it reserves each launch's measured worst cost until the reading after it ends. Codex and `agy` stop at the first quota sign.
- **Exit criteria.** Version 2 grows toward 43 tasks per kind only if version 1 shows repeatable scoring, judge agreement of at least 80%, complete records for at least 95% of runs, and a cost that fits the quota.

## Status

The design is complete and awaits the coordinator's approval. Nobody has packaged a task or started a run.

<!-- cspell:ignore bwrap numstat redactions -->
