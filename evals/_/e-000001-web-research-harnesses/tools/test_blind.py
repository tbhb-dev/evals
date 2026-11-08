# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns
# cspell:ignore claudes codexes

"""Tests for anonymous answer preparation and score restoration."""

import csv
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import blind


class BlindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.out = self.root / "blinded"
        self.map = self.root / "map.json"

    def answer(self):
        return {
            "answer": "A supported answer.", "confidence": "medium", "premise_ok": True,
            "claims": [{"text": "A claim.", "citations": [{"url": "/source", "quote": "Evidence."}]}],
            "tools_used": ["identifying-tool"],
        }

    def add_run(self, run_id="run-a", answer=None):
        run = self.runs / run_id
        run.mkdir()
        (run / "run.json").write_text(json.dumps({
            "system": "system-a", "question_id": "question-a", "extra": "discard",
        }), encoding="utf-8")
        (run / "answer.json").write_text(
            json.dumps(self.answer() if answer is None else answer), encoding="utf-8",
        )
        return run

    def prepare(self, scrub_file=None):
        blind.prepare(self.runs, self.out, self.map, scrub_file)
        return blind.read_json(self.map)

    def only_item(self):
        return blind.read_json(next(self.out.iterdir()))

    def write_scores(self, rows, fields=("label", "score", "notes")):
        scores = self.root / "scores.csv"
        with scores.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
        return scores

    def test_random_labels_independent_of_order_and_run_ids(self):
        first = self.add_run("run-a")
        second = self.add_run("run-b")
        labels = ["f" * 12, "a" * 12]
        written = []
        original = blind.write_json

        def record(stream, value):
            written.append(Path(stream.name).name)
            original(stream, value)

        with patch.object(Path, "iterdir", return_value=iter([first, second])):
            with patch.object(blind.secrets, "token_hex", side_effect=labels) as entropy:
                with patch.object(blind, "write_json", side_effect=record):
                    document = self.prepare()
        self.assertEqual(entropy.call_args_list, [unittest.mock.call(6)] * 2)
        self.assertEqual(written[1:], [f"{label}.json" for label in sorted(labels)])
        self.assertEqual(set(document["items"]), set(labels))
        first = first.rename(self.runs / "renamed-a")
        second = second.rename(self.runs / "renamed-b")
        with patch.object(Path, "iterdir", return_value=iter([second, first])):
            with patch.object(blind.secrets, "token_hex", side_effect=labels):
                blind.prepare(self.runs, self.root / "other-blinded", self.root / "other-map.json")
        other = blind.read_json(self.root / "other-map.json")
        self.assertEqual(set(other["items"]), set(labels))
        self.assertEqual(other["items"][labels[0]]["run_id"], "renamed-b")

    def test_fresh_labels_on_repeated_preparation(self):
        self.add_run()
        first = self.prepare()
        blind.prepare(self.runs, self.root / "other-blinded", self.root / "other-map.json")
        second = blind.read_json(self.root / "other-map.json")
        self.assertTrue(set(first["items"]).isdisjoint(second["items"]))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{12}", label) for label in first["items"]))

    def test_label_collision_retries(self):
        self.add_run("run-a")
        self.add_run("run-b")
        with patch.object(blind.secrets, "token_hex", side_effect=["a" * 12, "a" * 12, "b" * 12]):
            self.assertEqual(len(self.prepare()["items"]), 2)

    def test_only_allowed_fields_survive(self):
        answer = self.answer()
        answer["system"] = "discard"
        answer["claims"][0]["tool"] = "discard"
        answer["claims"][0]["citations"][0]["tool"] = "discard"
        self.add_run(answer=answer)
        document = self.prepare()
        item = self.only_item()
        self.assertEqual(set(item), {
            "question_id", "answer", "confidence", "premise_ok", "claims", "answer_status",
        })
        self.assertEqual(set(item["claims"][0]), {"text", "citations"})
        self.assertEqual(set(item["claims"][0]["citations"][0]), {"url", "quote"})
        self.assertEqual(item["answer_status"], "ok")
        self.assertIsNotNone(datetime.fromisoformat(document["created_at"]).utcoffset())
        self.assertEqual(next(iter(document["items"].values())), {
            "run_id": "run-a", "system": "system-a", "question_id": "question-a",
            "scrub_count": 0, "answer_status": "ok",
        })

    def test_missing_and_invalid_answers_remain_blinded(self):
        missing = self.add_run("missing")
        (missing / "answer.json").unlink()
        malformed = self.add_run("malformed")
        (malformed / "answer.json").write_text("{", encoding="utf-8")
        self.add_run("wrong-schema", {"answer": "incomplete"})
        document = self.prepare()
        self.assertEqual(len(document["items"]), 3)
        for label, metadata in document["items"].items():
            status = "missing" if metadata["run_id"] == "missing" else "invalid"
            self.assertEqual(metadata["answer_status"], status)
            self.assertEqual(blind.read_json(self.out / f"{label}.json"), {
                "question_id": "question-a", "answer": None, "confidence": None,
                "premise_ok": None, "claims": [], "answer_status": status,
            })

    def test_schema_validation(self):
        cases = [[], None, {}, {**self.answer(), "confidence": 0.8},
                 {**self.answer(), "confidence": "certain"},
                 {**self.answer(), "confidence": True},
                 {**self.answer(), "premise_ok": "yes"},
                 {**self.answer(), "tools_used": "tool"},
                 {**self.answer(), "claims": [{"text": "claim", "citations": [{}]}]}]
        for value in cases:
            with self.subTest(value=value):
                self.assertFalse(blind.valid_answer(value))

    def test_scrub_text_preserves_urls_quotes_and_word_boundaries(self):
        answer = self.answer()
        answer["answer"] = "CLAUDE Codex Antigravity Gemini GPT ChatGPT OpenAI Anthropic as an AI"
        answer["claims"][0]["text"] = "cLaUdE custom+term claudes codexes"
        citation = {"url": "/Claude/GPT-4", "quote": "Claude says GPT-4."}
        answer["claims"][0]["citations"] = [citation]
        self.add_run(answer=answer)
        scrub_file = self.root / "words.txt"
        scrub_file.write_text("custom+term\n\n", encoding="utf-8")
        document = self.prepare(scrub_file)
        item = self.only_item()
        self.assertEqual(item["answer"], " ".join(["[redacted]"] * 9))
        self.assertEqual(item["claims"][0]["text"], "[redacted] [redacted] claudes codexes")
        self.assertEqual(item["claims"][0]["citations"], [citation])
        self.assertEqual(next(iter(document["items"].values()))["scrub_count"], 11)

    def test_model_ids_are_fully_scrubbed(self):
        answer = self.answer()
        answer["answer"] = "gpt-4o GPT-5.2 claude-sonnet-4-5 GEMINI-2.5-pro."
        self.add_run(answer=answer)
        document = self.prepare()
        self.assertEqual(self.only_item()["answer"], "[redacted] [redacted] [redacted] [redacted].")
        self.assertEqual(next(iter(document["items"].values()))["scrub_count"], 4)

    def test_map_inside_output_is_refused(self):
        for map_path in (self.out, self.out / "map.json", self.out / "nested" / "map.json"):
            with self.subTest(map_path=map_path.name), self.assertRaises(ValueError):
                blind.prepare(self.runs, self.out, map_path)
        self.assertFalse(self.out.exists())

    def test_symlink_cannot_hide_map_inside_output(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            blind.prepare(self.runs, self.out, alias / "blinded" / "map.json")

    def test_existing_output_or_map_is_refused_without_changes(self):
        self.add_run()
        self.out.mkdir()
        marker = self.out / "marker"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.map.exists())
        self.map.write_text("keep", encoding="utf-8")
        other = self.root / "other-blinded"
        with self.assertRaises(ValueError):
            blind.prepare(self.runs, other, self.map)
        self.assertEqual(self.map.read_text(encoding="utf-8"), "keep")
        self.assertFalse(other.exists())

    def test_unblind_round_trip(self):
        self.add_run("run-a")
        self.add_run("run-b")
        mapping = self.prepare()["items"]
        labels = list(reversed(mapping))
        scores = self.write_scores(
            [["8", label, "two, lines\nwith text"] for label in labels],
            fields=("score", "label", "notes"),
        )
        graded = self.root / "graded.csv"
        blind.unblind(self.map, scores, graded)
        with graded.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, ["score", "run_id", "system", "question_id", "notes"])
            rows = list(reader)
        self.assertEqual([row["run_id"] for row in rows], [mapping[label]["run_id"] for label in labels])
        for row in rows:
            self.assertEqual(row["score"], "8")
            self.assertEqual(row["notes"], "two, lines\nwith text")
            self.assertEqual(row["system"], "system-a")
            self.assertEqual(row["question_id"], "question-a")

    def test_unknown_missing_and_duplicate_labels_fail(self):
        self.add_run()
        label = next(iter(self.prepare()["items"]))
        for rows in ([['unknown', "1", ""]], [["", "1", ""]], [],
                     [[label, "1", ""], [label, "2", ""]]):
            with self.subTest(rows=rows):
                scores = self.write_scores(rows)
                graded = self.root / "graded.csv"
                with self.assertRaises(ValueError):
                    blind.unblind(self.map, scores, graded)
                self.assertFalse(graded.exists())

    def test_missing_label_column_fails(self):
        self.add_run()
        self.prepare()
        scores = self.write_scores([["1"]], fields=("score",))
        with self.assertRaises(ValueError):
            blind.unblind(self.map, scores, self.root / "graded.csv")

    def test_cli_prepare_and_unblind(self):
        self.add_run()
        blind.main(["prepare", "--runs", str(self.runs), "--out", str(self.out), "--map", str(self.map)])
        label = next(iter(blind.read_json(self.map)["items"]))
        scores = self.write_scores([[label, "1", ""]])
        graded = self.root / "graded.csv"
        blind.main(["unblind", "--map", str(self.map), "--scores", str(scores), "--out", str(graded)])
        self.assertTrue(graded.exists())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            blind.main(["prepare", "--runs", str(self.runs), "--out", str(self.out), "--map", str(self.map)])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
