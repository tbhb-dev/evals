# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns

"""Prepare anonymous answers and join blind scores back to run metadata."""

import argparse
import csv
import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_WORDS = (
    "Claude", "Codex", "Antigravity", "Gemini", "GPT", "ChatGPT",
    "OpenAI", "Anthropic", "as an AI",
)
CONFIDENCE = ("high", "medium", "low")
MODEL_IDS = r"(?:gpt-\d|claude-[a-z]|gemini-\d)[a-z0-9]*(?:[._-][a-z0-9]+)*"


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, parse_constant=reject_constant)


def scrub_pattern(scrub_file):
    words = list(DEFAULT_WORDS)
    if scrub_file is not None:
        words.extend(scrub_file.read_text(encoding="utf-8").splitlines())
    literals = sorted({word.strip() for word in words if word.strip()}, key=len, reverse=True)
    alternatives = [MODEL_IDS, *(re.escape(word) for word in literals)]
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)


def valid_answer(value):
    if not isinstance(value, dict):
        return False
    if (
        not isinstance(value.get("answer"), str)
        or value.get("confidence") not in CONFIDENCE
        or type(value.get("premise_ok")) is not bool
        or not isinstance(value.get("claims"), list)
        or not isinstance(value.get("tools_used"), list)
        or not all(isinstance(tool, str) for tool in value["tools_used"])
    ):
        return False
    for claim in value["claims"]:
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("text"), str)
            or not isinstance(claim.get("citations"), list)
        ):
            return False
        for citation in claim["citations"]:
            if not isinstance(citation, dict) or not all(
                isinstance(citation.get(field), str) for field in ("url", "quote")
            ):
                return False
    return True


def blind_answer(path, question_id, pattern):
    item = {
        "question_id": question_id, "answer": None, "confidence": None,
        "premise_ok": None, "claims": [], "answer_status": "invalid",
    }
    try:
        answer = read_json(path)
    except FileNotFoundError:
        item["answer_status"] = "missing"
        return item, 0
    except (OSError, ValueError, UnicodeError):
        return item, 0
    if not valid_answer(answer):
        return item, 0
    item["answer_status"] = "ok"
    item["confidence"] = answer["confidence"]
    item["premise_ok"] = answer["premise_ok"]
    item["answer"], count = pattern.subn("[redacted]", answer["answer"])
    for claim in answer["claims"]:
        text, replacements = pattern.subn("[redacted]", claim["text"])
        count += replacements
        item["claims"].append({
            "text": text,
            "citations": [
                {field: citation[field] for field in ("url", "quote")}
                for citation in claim["citations"]
            ],
        })
    return item, count


def exists(path):
    return path.exists() or path.is_symlink()


def write_json(stream, value):
    json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
    stream.write("\n")


def prepare(runs, out, map_path, scrub_file=None):
    if map_path.resolve().is_relative_to(out.resolve()):
        raise ValueError("Map must be outside the blinded directory")
    if exists(out) or exists(map_path):
        raise ValueError("Blinded directory and map must not already exist")
    pattern = scrub_pattern(scrub_file)
    items = {}
    mapping = {}
    for run in runs.iterdir():
        if not run.is_dir():
            continue
        metadata = read_json(run / "run.json")
        if not isinstance(metadata, dict) or not all(
            isinstance(metadata.get(field), str) and metadata[field]
            for field in ("system", "question_id")
        ):
            raise ValueError("Run metadata requires system and question_id strings")
        label = secrets.token_hex(6)
        while label in items:
            label = secrets.token_hex(6)
        item, count = blind_answer(run / "answer.json", metadata["question_id"], pattern)
        items[label] = item
        mapping[label] = {
            "run_id": run.name, "system": metadata["system"],
            "question_id": metadata["question_id"], "scrub_count": count,
            "answer_status": item["answer_status"],
        }
    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": {label: mapping[label] for label in sorted(mapping)},
    }
    out.mkdir(parents=True, exist_ok=False)
    map_created = False
    try:
        with map_path.open("x", encoding="utf-8") as stream:
            map_created = True
            write_json(stream, document)
        for label in sorted(items):
            with (out / f"{label}.json").open("x", encoding="utf-8") as stream:
                write_json(stream, items[label])
    except BaseException:
        shutil.rmtree(out)
        if map_created:
            map_path.unlink()
        raise


def unblind(map_path, scores, out):
    mapping = read_json(map_path)["items"]
    metadata_columns = ["run_id", "system", "question_id"]
    with scores.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if not fields or fields.count("label") != 1 or len(set(fields)) != len(fields):
            raise ValueError("Scores require unique columns including label")
        if any(field in fields for field in metadata_columns):
            raise ValueError("Score columns conflict with run metadata")
        output_fields = []
        for field in fields:
            output_fields.extend(metadata_columns if field == "label" else [field])
        rows = []
        seen = set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Score row does not match its columns")
            label = row.pop("label")
            if not label or label not in mapping:
                raise ValueError("Unknown or missing score label")
            if label in seen:
                raise ValueError("Duplicate score label")
            seen.add(label)
            row.update({field: mapping[label][field] for field in metadata_columns})
            rows.append(row)
        if seen != set(mapping):
            raise ValueError("Scores are missing labels from the map")
    with out.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Create blinded answers")
    prepare_parser.add_argument("--runs", type=Path, required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    prepare_parser.add_argument("--map", type=Path, required=True)
    prepare_parser.add_argument("--scrub-file", type=Path)
    unblind_parser = commands.add_parser("unblind", help="Restore run metadata to scores")
    unblind_parser.add_argument("--map", type=Path, required=True)
    unblind_parser.add_argument("--scores", type=Path, required=True)
    unblind_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.runs, args.out, args.map, args.scrub_file)
        else:
            unblind(args.map, args.scores, args.out)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Avoid printing source data or filesystem locations in errors.
        parser.exit(2, f"blind: {type(error).__name__}: operation failed\n")


if __name__ == "__main__":
    main()
