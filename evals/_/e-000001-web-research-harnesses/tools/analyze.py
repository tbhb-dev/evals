#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns
# cspell:ignore pvalue
"""Analyze graded runs using question-clustered uncertainty estimates."""

import argparse
import csv
import itertools
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


COLUMNS = (
    "run_id system question_id stratum drafted_by round accuracy citation recency "
    "hallucinations confidence wall_seconds tokens cost_usd judge"
).split()
PROBABILITIES = {"high": 0.9, "medium": 0.6, "low": 0.3}
UNREPORTED = "unreported"


@dataclass(frozen=True)
class Grade:
    judge: str
    accuracy: int
    citation: int
    recency: int | None
    hallucinations: int


@dataclass(frozen=True)
class Run:
    run_id: str
    system: str
    question_id: str
    stratum: str
    drafted_by: str
    round: str
    confidence: str
    wall_seconds: float
    tokens: int | None
    cost_usd: float | None
    grades: tuple[Grade, ...]

    def mean(self, field):
        values = [getattr(grade, field) for grade in self.grades]
        values = [value for value in values if value is not None]
        return statistics.fmean(values) if values else None

    @property
    def accuracy(self):
        return self.mean("accuracy")


def number(value, field, integer=False, maximum=None, optional=False):
    if optional and not value:
        return None
    try:
        result = int(value) if integer else float(value)
    except ValueError:
        raise ValueError(f"{field} must be a number") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field} must be at most {maximum}")
    return result


def read_runs(path):
    metadata = {}
    grades = defaultdict(dict)
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not set(COLUMNS) <= set(reader.fieldnames):
            raise ValueError("CSV is missing required columns")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV has duplicate column names")
        for line, raw in enumerate(reader, 2):
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError("row has the wrong number of fields")
                row = {key: value.strip() for key, value in raw.items()}
                for field in COLUMNS:
                    if field not in {"recency", "tokens", "cost_usd"} and not row[field]:
                        raise ValueError(f"{field} is required")
                if row["stratum"] not in {"S", "R", "N", "M", "F"}:
                    raise ValueError("invalid stratum")
                if row["confidence"] not in PROBABILITIES:
                    raise ValueError("invalid confidence")
                if row["stratum"] != "R" and row["recency"]:
                    raise ValueError("recency must be empty outside stratum R")
                grade = Grade(
                    row["judge"],
                    number(row["accuracy"], "accuracy", True, 2),
                    number(row["citation"], "citation", True, 3),
                    number(row["recency"], "recency", True, 2, row["stratum"] != "R"),
                    number(row["hallucinations"], "hallucinations", True),
                )
                details = {field: row[field] for field in (
                    "run_id", "system", "question_id", "stratum", "drafted_by",
                    "round", "confidence",
                )}
                details.update(
                    wall_seconds=number(row["wall_seconds"], "wall_seconds"),
                    tokens=number(row["tokens"], "tokens", True, optional=True),
                    cost_usd=number(row["cost_usd"], "cost_usd", optional=True),
                )
                key = row["run_id"]
                if key in metadata and metadata[key] != details:
                    raise ValueError("run metadata differs between judges")
                if grade.judge in grades[key]:
                    raise ValueError("duplicate judge for a run")
                metadata[key] = details
                grades[key][grade.judge] = grade
            except ValueError as error:
                raise ValueError(f"CSV row {line}: {error}") from None
    if not metadata:
        raise ValueError("CSV contains no graded runs")
    return [Run(**metadata[key], grades=tuple(grades[key][judge]
            for judge in sorted(grades[key]))) for key in sorted(metadata)]


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def interval(values):
    return percentile(values, 0.025), percentile(values, 0.975)


def question_groups(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[run.question_id].append(run.accuracy * 50)
    return groups


def accuracy_summary(runs, rng, resamples):
    groups = question_groups(runs)
    clusters = [(sum(groups[key]), len(groups[key])) for key in sorted(groups)]
    samples = []
    for _ in range(resamples):
        selected = rng.choices(clusters, k=len(clusters))
        samples.append(sum(total for total, _ in selected)
                       / sum(count for _, count in selected))
    low, high = interval(samples)
    return {
        "runs": len(runs), "questions": len(groups),
        "accuracy_pct": statistics.fmean(run.accuracy * 50 for run in runs),
        "ci_low_pct": low, "ci_high_pct": high,
    }


def optional_mean(values):
    reported = [value for value in values if value is not None]
    return statistics.fmean(reported) if reported else UNREPORTED


def system_summary(runs, rng, resamples):
    result = accuracy_summary(runs, rng, resamples)
    times = [run.wall_seconds for run in runs]
    result.update(
        citation_mean=statistics.fmean(run.mean("citation") for run in runs),
        recency_mean=optional_mean(run.mean("recency") for run in runs if run.stratum == "R"),
        hallucinations_per_run=statistics.fmean(run.mean("hallucinations") for run in runs),
        hallucination_share=statistics.fmean(run.mean("hallucinations") > 0 for run in runs),
        brier=statistics.fmean((PROBABILITIES[run.confidence] - (run.accuracy == 2)) ** 2
                              for run in runs),
        wall_seconds_median=statistics.median(times),
        wall_seconds_p90=percentile(times, 0.9),
        tokens_mean=optional_mean(run.tokens for run in runs),
        tokens_reported=sum(run.tokens is not None for run in runs),
        cost_usd_mean=optional_mean(run.cost_usd for run in runs),
        cost_reported=sum(run.cost_usd is not None for run in runs),
    )
    return result


def sign_flip_pvalue(differences, rng, flips=10000):
    observed = abs(statistics.fmean(differences))
    if observed == 0:
        return 1.0
    extreme = 0
    for _ in range(flips):
        permuted = abs(statistics.fmean(value * rng.choice((-1, 1))
                                       for value in differences))
        extreme += permuted >= observed - 1e-12
    return (extreme + 1) / (flips + 1)


def pairwise_summary(left, right, rng, resamples):
    left_groups, right_groups = question_groups(left), question_groups(right)
    shared = sorted(left_groups.keys() & right_groups.keys())
    result = {"questions": len(shared)}
    if not shared:
        result.update(difference_pp=UNREPORTED, ci_low_pp=UNREPORTED,
                      ci_high_pp=UNREPORTED, p_value=UNREPORTED)
        return result
    differences = [statistics.fmean(left_groups[key]) - statistics.fmean(right_groups[key])
                   for key in shared]
    low, high = interval([statistics.fmean(rng.choices(differences, k=len(differences)))
                          for _ in range(resamples)])
    result.update(difference_pp=statistics.fmean(differences), ci_low_pp=low,
                  ci_high_pp=high, p_value=sign_flip_pvalue(differences, rng))
    return result


def judge_rows(runs, families):
    scores = defaultdict(list)
    for run in runs:
        for grade in run.grades:
            scores[grade.judge, run.system].append((run.question_id, grade.accuracy * 50))
    rows = []
    for (judge, system), values in sorted(scores.items()):
        rows.append(dict(kind="accuracy", judge=judge, system=system, runs=len(values),
                         questions=len({question for question, _ in values}),
                         accuracy_pct=statistics.fmean(value for _, value in values),
                         other_judges_accuracy_pct=UNREPORTED, self_preference_pp=UNREPORTED))
    for judge in sorted({grade.judge for run in runs for grade in run.grades}):
        system = families.get(judge)
        own, others, questions = [], [], set()
        for run in runs:
            by_judge = {grade.judge: grade.accuracy * 50 for grade in run.grades}
            if run.system == system and judge in by_judge and len(by_judge) > 1:
                own.append(by_judge.pop(judge))
                others.append(statistics.fmean(by_judge.values()))
                questions.add(run.question_id)
        rows.append(dict(kind="self_preference", judge=judge, system=system or UNREPORTED,
                         runs=len(own), questions=len(questions), accuracy_pct=optional_mean(own),
                         other_judges_accuracy_pct=optional_mean(others),
                         self_preference_pp=statistics.fmean(a - b for a, b in zip(own, others))
                         if own else UNREPORTED))
    return rows


def display(value):
    if isinstance(value, float):
        return format(value, ".10g")
    return str(value)


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: display(value) for key, value in row.items()} for row in rows)


def markdown_cell(value):
    return display(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def write_markdown(path, summaries, pairs, seed, resamples):
    fields = list(summaries[0])
    lines = ["# Graded run summary", "",
             f"Seed: {seed}. Bootstrap resamples: {resamples}. Sign flips: 10000. Intervals are 95% percentile bootstrap intervals over questions, keeping all runs of each sampled question together.", "",
             "Accuracy is scaled to percent. Summary means weight runs equally after averaging judges. Pairwise differences weight shared questions equally and are in percentage points (first system minus second). Systems are listed by label, without ranking. P-values are unadjusted for multiple comparisons.", "",
             "Brier scores use high=0.9, medium=0.6, low=0.3 and correct only when the averaged accuracy equals 2. Any positive averaged hallucination count counts as a run with hallucinations. Missing optional measurements are excluded from means; unreported means no measurements. A single question gives a degenerate interval and cannot estimate variation across questions.", "",
             "| " + " | ".join(fields) + " |",
             "| " + " | ".join("---" for _ in fields) + " |"]
    for row in summaries:
        lines.append("| " + " | ".join(markdown_cell(row[field]) for field in fields) + " |")
    lines += ["", "## Comparisons", ""]
    by_system = {row["system"]: row for row in summaries}
    if not pairs:
        lines.append("No system pairs are available.")
    for pair in pairs:
        left, right = by_system[pair["system_a"]], by_system[pair["system_b"]]
        label = f"{markdown_cell(pair['system_a'])} versus {markdown_cell(pair['system_b'])}"
        overlap = max(left["ci_low_pct"], right["ci_low_pct"]) <= min(left["ci_high_pct"], right["ci_high_pct"])
        reasons = []
        if overlap:
            reasons.append("the systems' accuracy CIs overlap")
        if pair["questions"] == 0:
            lines.append(f"{label}: no shared questions; paired comparison is unreported."
                         + (" The systems' accuracy CIs overlap: not distinguishable at this sample size." if overlap else ""))
        else:
            if pair["ci_low_pp"] <= 0 <= pair["ci_high_pp"]:
                reasons.append("the paired difference CI overlaps zero")
            if pair["questions"] < 2:
                reasons.append("only one shared question is available")
            if pair["p_value"] >= 0.05:
                reasons.append("the sign-flip p-value is at least 0.05")
            statement = ("; ".join(reasons) + ": not distinguishable at this sample size."
                         if reasons else "The paired CI excludes zero; this is an unadjusted comparison, not a ranking.")
            lines.append(f"{label}: difference {display(pair['difference_pp'])} pp, 95% CI [{display(pair['ci_low_pp'])}, {display(pair['ci_high_pp'])}], p={display(pair['p_value'])}, shared questions={pair['questions']}. {statement}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def analyze(runs, out, seed=0, resamples=10000, families=None):
    if resamples < 1:
        raise ValueError("resamples must be positive")
    families = families or {}
    systems = sorted({run.system for run in runs})
    judges = {grade.judge for run in runs for grade in run.grades}
    if not set(families) <= judges or not set(families.values()) <= set(systems):
        raise ValueError("judge-family labels must occur in the input")
    rng = random.Random(seed)
    grouped = {system: [run for run in runs if run.system == system] for system in systems}
    summaries = [dict(system=system, **system_summary(grouped[system], rng, resamples))
                 for system in systems]
    strata, drafters = [], []
    for field, rows in (("stratum", strata), ("drafted_by", drafters)):
        for system in systems:
            for label in sorted({getattr(run, field) for run in grouped[system]}):
                subset = [run for run in grouped[system] if getattr(run, field) == label]
                rows.append({"system": system, field: label, **accuracy_summary(subset, rng, resamples)})
    pairs = [dict(system_a=left, system_b=right,
                  **pairwise_summary(grouped[left], grouped[right], rng, resamples))
             for left, right in itertools.combinations(systems, 2)]
    consistency = []
    for system in systems:
        for question, values in sorted(question_groups(grouped[system]).items()):
            consistency.append(dict(system=system, question_id=question, runs=len(values),
                                    consistent=len(set(values)) == 1))
    per_judge = judge_rows(runs, families)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("summary", summaries), ("by_stratum", strata),
                       ("by_drafter", drafters), ("consistency", consistency),
                       ("per_judge", per_judge)):
        write_csv(out / f"{name}.csv", rows, list(rows[0]))
    write_csv(out / "pairwise.csv", pairs,
              ["system_a", "system_b", "questions", "difference_pp", "ci_low_pp", "ci_high_pp", "p_value"])
    write_markdown(out / "summary.md", summaries, pairs, seed, resamples)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graded_csv", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--judge-family", action="append", default=[], metavar="JUDGE=SYSTEM")
    args = parser.parse_args(argv)
    try:
        families = {}
        for entry in args.judge_family:
            judge, separator, system = entry.partition("=")
            if not separator or not judge or not system or judge in families:
                raise ValueError("judge-family must be a unique JUDGE=SYSTEM mapping")
            families[judge] = system
        analyze(read_runs(args.graded_csv), args.out, args.seed, args.resamples, families)
    except (ValueError, OSError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
