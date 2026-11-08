# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns
# cspell:ignore pvalue

"""Synthetic coverage for the graded-run analysis CLI."""

import csv
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import analyze


def row(run_id="run-a", system="system-a", question_id="q-a", **changes):
    result = dict(run_id=run_id, system=system, question_id=question_id,
                  stratum="S", drafted_by="drafter-a", round="1", accuracy="2",
                  citation="3", recency="", hallucinations="0", confidence="high",
                  wall_seconds="10", tokens="", cost_usd="", judge="judge-a")
    result.update(changes)
    return result


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "graded.csv"

    def load(self, rows):
        with self.source.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=analyze.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return analyze.read_runs(self.source)

    def csv_rows(self, directory, name):
        with (directory / name).open(newline="", encoding="utf-8") as source:
            return list(csv.DictReader(source))

    def test_seed_determinism_and_cli_outputs(self):
        rows = [row(f"run-{system}-{question}-{repeat}", system, f"q-{question}",
                    accuracy=str((question + repeat) % 3))
                for system in ("system-a", "system-b")
                for question in range(4) for repeat in range(2)]
        self.load(rows)
        first, second = self.root / "first", self.root / "second"
        for output in (first, second):
            completed = subprocess.run(
                [sys.executable, str(Path(analyze.__file__)), str(self.source),
                 "--out", str(output), "--seed", "19", "--resamples", "200",
                 "--judge-family", "judge-a=system-a"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = {"summary.csv", "summary.md", "by_stratum.csv", "by_drafter.csv",
                    "pairwise.csv", "consistency.csv", "per_judge.csv"}
        self.assertEqual({path.name for path in first.iterdir()}, expected)
        for name in expected:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        # Sorting run and judge labels makes a seed independent of input row order.
        reordered = self.load(list(reversed(rows)))
        analyze.analyze(reordered, second, seed=19, resamples=200,
                        families={"judge-a": "system-a"})
        for name in expected:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        self.assertIn("not distinguishable at this sample size", (first / "summary.md").read_text())
        self.assertEqual(self.csv_rows(first, "pairwise.csv")[0]["p_value"], "1")
        self.assertTrue(all(item["consistent"] == "False"
                            for item in self.csv_rows(first, "consistency.csv")))

    def test_resampling_keeps_question_clusters_and_run_weights(self):
        runs = self.load([row(f"repeat-{index}", accuracy="0") for index in range(9)]
                         + [row("single", question_id="q-b", accuracy="2")])

        class EnumeratedSamples:
            def __init__(self):
                self.index = 0

            def choices(inner, population, k):
                self.assertEqual(population, [(0.0, 9), (100.0, 1)])
                self.assertEqual(k, 2)
                combinations = [(0, 0), (0, 1), (1, 0), (1, 1)]
                selection = combinations[inner.index % 4]
                inner.index += 1
                return [population[index] for index in selection]

        result = analyze.accuracy_summary(runs, EnumeratedSamples(), 400)
        self.assertEqual(result["accuracy_pct"], 10)
        self.assertEqual((result["ci_low_pct"], result["ci_high_pct"]), (0, 100))
        # With one question, varying runs must travel together in every draw.
        runs = self.load([row("first", accuracy="0"), row("second", accuracy="2")])
        result = analyze.accuracy_summary(runs, random.Random(1), 100)
        self.assertEqual((result["ci_low_pct"], result["ci_high_pct"]), (50, 50))

    def test_multi_judge_averaging_and_self_preference(self):
        runs = self.load([
            row(accuracy="2", citation="3", hallucinations="0"),
            row(judge="judge-b", accuracy="0", citation="1", hallucinations="2"),
            row("run-b", question_id="q-b", accuracy="2", citation="2"),
        ])
        self.assertEqual(len(runs), 2)
        result = analyze.system_summary(runs, random.Random(2), 100)
        self.assertEqual(result["accuracy_pct"], 75)
        self.assertEqual(result["citation_mean"], 2)
        self.assertEqual(result["hallucinations_per_run"], 0.5)
        self.assertEqual(result["hallucination_share"], 0.5)
        self.assertAlmostEqual(result["brier"], (0.9 ** 2 + 0.1 ** 2) / 2)
        reports = analyze.judge_rows(runs, {"judge-a": "system-a"})
        accuracy = {item["judge"]: item for item in reports if item["kind"] == "accuracy"}
        self.assertEqual(accuracy["judge-a"]["accuracy_pct"], 100)
        self.assertEqual(accuracy["judge-b"]["accuracy_pct"], 0)
        preference = {item["judge"]: item for item in reports if item["kind"] == "self_preference"}
        self.assertEqual(preference["judge-a"]["runs"], 1)
        self.assertEqual(preference["judge-a"]["self_preference_pp"], 100)
        self.assertEqual(preference["judge-b"]["self_preference_pp"], "unreported")

    def test_empty_measurements_and_brier(self):
        runs = self.load([
            row("high", accuracy="2", confidence="high", wall_seconds="10"),
            row("medium", accuracy="1", confidence="medium", wall_seconds="20"),
            row("low", accuracy="0", confidence="low", wall_seconds="30"),
        ])
        result = analyze.system_summary(runs, random.Random(3), 100)
        for field in ("recency_mean", "tokens_mean", "cost_usd_mean"):
            self.assertEqual(result[field], "unreported")
        self.assertAlmostEqual(result["brier"], (0.01 + 0.36 + 0.09) / 3)
        self.assertEqual(result["wall_seconds_median"], 20)
        self.assertEqual(result["wall_seconds_p90"], 28)
        out = self.root / "output"
        analyze.analyze(runs, out, resamples=10)
        saved = self.csv_rows(out, "summary.csv")[0]
        for field in ("recency_mean", "tokens_mean", "cost_usd_mean"):
            self.assertEqual(saved[field], "unreported")
        self.assertEqual(self.csv_rows(out, "pairwise.csv"), [])

    def test_recency_and_partially_reported_resources(self):
        runs = self.load([
            row(stratum="R", recency="2", tokens="100", cost_usd="0.2"),
            row(stratum="R", recency="0", tokens="100", cost_usd="0.2", judge="judge-b"),
            row("run-b", question_id="q-b"),
            row("run-c", question_id="q-c", stratum="R", recency="2", tokens="0", cost_usd="0"),
        ])
        result = analyze.system_summary(runs, random.Random(4), 100)
        self.assertEqual(result["recency_mean"], 1.5)
        self.assertEqual(result["tokens_mean"], 50)
        self.assertEqual(result["cost_usd_mean"], 0.1)
        self.assertEqual(result["tokens_reported"], 2)
        self.assertEqual(result["cost_reported"], 2)

    def test_sign_flip_obvious_and_no_difference(self):
        p_value = analyze.sign_flip_pvalue([100] * 20, random.Random(5))
        self.assertGreater(p_value, 0)
        self.assertLess(p_value, 0.001)
        self.assertEqual(p_value, analyze.sign_flip_pvalue([100] * 20, random.Random(5)))
        self.assertEqual(analyze.sign_flip_pvalue([0] * 20, random.Random(5)), 1)
        self.assertEqual(analyze.sign_flip_pvalue([-100, 100], random.Random(5)), 1)
        self.assertEqual(analyze.sign_flip_pvalue([100], random.Random(5)), 1)

    def test_pairwise_equal_question_weight_and_shared_questions(self):
        runs = self.load(
            [row(f"a-{index}", accuracy="2") for index in range(9)]
            + [row("a-b", question_id="q-b", accuracy="0"),
               row("a-only", question_id="q-only", accuracy="2"),
               row("b-a", system="system-b", accuracy="0"),
               row("b-b", system="system-b", question_id="q-b", accuracy="0")]
        )
        left = [run for run in runs if run.system == "system-a"]
        right = [run for run in runs if run.system == "system-b"]
        result = analyze.pairwise_summary(left, right, random.Random(6), 1000)
        self.assertEqual(result["questions"], 2)
        self.assertEqual(result["difference_pp"], 50)
        self.assertEqual((result["ci_low_pp"], result["ci_high_pp"]), (0, 100))
        self.assertAlmostEqual(result["p_value"], 1)
        unmatched = [run for run in left if run.question_id == "q-only"]
        result = analyze.pairwise_summary(unmatched, right, random.Random(6), 100)
        self.assertEqual(result["questions"], 0)
        self.assertEqual(result["p_value"], "unreported")

    def test_overlap_wording_even_when_paired_ci_excludes_zero(self):
        summaries = [dict(system="system-a", ci_low_pct=30, ci_high_pct=90),
                     dict(system="system-b", ci_low_pct=10, ci_high_pct=60)]
        pairs = [dict(system_a="system-a", system_b="system-b", questions=20,
                      difference_pp=20, ci_low_pp=10, ci_high_pp=30, p_value=0.001)]
        target = self.root / "summary.md"
        analyze.write_markdown(target, summaries, pairs, 0, 100)
        text = target.read_text()
        self.assertIn("the systems' accuracy CIs overlap", text)
        self.assertIn("not distinguishable at this sample size", text)
        # Paired intervals touching zero also require the wording independently.
        summaries[0].update(ci_low_pct=70, ci_high_pct=90)
        pairs[0].update(ci_low_pp=0)
        analyze.write_markdown(target, summaries, pairs, 0, 100)
        text = target.read_text()
        self.assertIn("the paired difference CI overlaps zero", text)
        self.assertIn("not distinguishable at this sample size", text)

    def test_stratum_and_drafter_summaries(self):
        runs = self.load([
            row("a", accuracy="0", drafted_by="drafter-a"),
            row("b", question_id="q-b", accuracy="2", stratum="R", recency="1",
                drafted_by="drafter-b"),
        ])
        output = self.root / "output"
        analyze.analyze(runs, output, resamples=20)
        for name, field, expected in (
            ("by_stratum.csv", "stratum", {"S": "0", "R": "100"}),
            ("by_drafter.csv", "drafted_by", {"drafter-a": "0", "drafter-b": "100"}),
        ):
            rows = self.csv_rows(output, name)
            self.assertEqual({item[field]: item["accuracy_pct"] for item in rows}, expected)
            self.assertTrue(all(item["ci_low_pct"] == item["ci_high_pct"] for item in rows))

    def test_invalid_input(self):
        for changes in (
            {"accuracy": "3"}, {"accuracy": "1.5"}, {"citation": "4"},
            {"hallucinations": "-1"}, {"wall_seconds": "nan"}, {"cost_usd": "inf"},
            {"tokens": "-1"}, {"confidence": "unknown"}, {"stratum": "X"},
            {"stratum": "R", "recency": ""}, {"recency": "1"}, {"judge": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load([row(**changes)])
        with self.assertRaisesRegex(ValueError, "duplicate judge"):
            self.load([row(), row()])
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            self.load([row(), row(judge="judge-b", wall_seconds="11")])
        with self.assertRaisesRegex(ValueError, "no graded runs"):
            self.load([])
        runs = self.load([row()])
        with self.assertRaisesRegex(ValueError, "positive"):
            analyze.analyze(runs, self.root / "output", resamples=0)
        with self.assertRaisesRegex(ValueError, "labels"):
            analyze.analyze(runs, self.root / "output", families={"unknown": "system-a"})


if __name__ == "__main__":
    unittest.main()
