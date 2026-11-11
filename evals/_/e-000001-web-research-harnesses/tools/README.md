# Grading tools

## Citation checker

`citecheck.py` fetches every URL that an answer cites and looks for the quoted text on that page. It follows HTTP and HTTPS redirects to record each final status code. Whether a source supports its claim is out of scope. A separate grading pass scores that.

The tool fetches each URL once per invocation, at most four at a time, with a 20-second timeout. It keeps at most 5,000,000 bytes of a body. For a larger page it records an error and matches quotes against that prefix. Each record includes the fetch time in Coordinated Universal Time and a hash of the body. The archive folder keeps each body once, under its hash, so a grader can repeat the check later. A failed body read still counts as live when the status was a success.

Before any request, and again for every redirect, the tool resolves the host and refuses it when any address falls outside the public internet: loopback, link-local and metadata, private ranges, the shared address space at 100.64.0.0/10, IPv6 unique local, and multicast. A refused URL becomes an error record and the tool never requests it, which keeps internal pages out of the archive. The connection itself resolves and checks the host once more and then connects to that checked address, which defeats DNS rebinding between the check and the connect. Proxies stay off. The checked address is the one the socket connects to.

It tries an exact match first. If that fails, it strips markup, folds case, width and typographic quotes, collapses whitespace, and tries again.

Run `python3 citecheck.py --out results answer.json` with one or more answer files, each with a unique name. The tool writes `<input-stem>.citations.json` for each. It exits with code 2 when an input holds malformed JSON or breaks the answer schema, after it processes the valid inputs. Network and URL errors go into the records and never stop a run. It needs Python 3.12 or newer and nothing beyond the standard library.

To run the tests from the repository root, use `python3 -m unittest discover -s evals/_/e-000001-web-research-harnesses/tools -v`. They inject fetches and use an in-memory transport, so they work offline.

## Analysis tool

`analyze.py` turns graded runs into the report tables. Run `python3 analyze.py graded.csv --out reports --seed 0 --resamples 10000` with Python 3.12 or newer and nothing beyond the standard library. Repeat `--judge-family judgeLabel=systemLabel` to tell it which judge shares a family with which system.

One judge can share its family with two systems. Each pair then gets its own self-preference row.

Keep graded data and reports out of this repository.

Each CSV row holds one judge's score for one run, with these columns: `run_id`, `system`, `question_id`, `stratum` (`S`, `R`, `N`, `M` or `F`), `drafted_by`, `round`, `accuracy` (0 to 2), `citation` (0 to 3), `recency` (0 to 2 for R questions, empty for the rest), `hallucinations`, `confidence` (`high`, `medium` or `low`), `wall_seconds`, `tokens` (may be empty), `cost_usd` (may be empty) and `judge`. A run ID stays the same across judges, and the tool rejects a second score from the same judge for one run.

The tool averages the judges' grades within each run first and then weights runs equally. `summary.csv` and `summary.md` give each system's accuracy as a percent with a 95% interval, mean citation and recency scores, hallucinations per run, the share of runs with any hallucination, a Brier score, median and p90 wall time, and mean tokens and cost. Brier uses 0.9, 0.6 and 0.3 for the three confidence levels, and a run counts as correct only when its averaged accuracy is 2. Missing tokens or cost drop out of the means, and a column with no reports reads `unreported`.

Intervals come from a bootstrap that draws whole questions with replacement and keeps all runs of each drawn question together. `by_stratum.csv` and `by_drafter.csv` repeat the accuracy interval for each stratum and each drafter. With one question the interval is one point, which says nothing about variation between questions.

`pairwise.csv` compares each pair of systems over their shared questions, weighting questions equally, in percentage points (first system minus second). For each pair it reports a paired bootstrap interval and a two-sided sign-flip p-value from 10000 seeded draws, unadjusted for the number of pairs. The Markdown calls a pair "not distinguishable at this sample size" when the two accuracy intervals overlap or the paired interval contains zero, and it never ranks systems.

`consistency.csv` says whether every run of a system on a question got the same averaged accuracy. `per_judge.csv` keeps each judge's accuracy for each system before any averaging. Its self-preference row compares a judge's scores for its own family's system with the other judges' scores for the same runs. Treat a positive value as a description, not proof of bias.

The same seed and input give identical reports, even with the rows shuffled. Run the tests with `python3 -m unittest discover -s evals/_/e-000001-web-research-harnesses/tools -v`.

## Blinding tool

`blind.py` hides which system wrote each answer before judges see it. Run `python3 blind.py prepare --runs <dir> --out <blinded-dir> --map <map.json>`, with `--scrub-file <words.txt>` for extra terms, one per line. Each run folder holds `run.json` and `answer.json`.

Every run becomes one file named by a random label. The file keeps the question ID, the answer, confidence, `premise_ok`, the claims with their citations, and an `answer_status` of `ok`, `missing` or `invalid`. It drops `tools_used` and all run metadata, because tool names give the harness away. A missing or malformed answer still gets a file, so judges score it as a failure without learning why.

The scrub replaces harness, model and vendor names, and model IDs, with `[redacted]` in answer and claim text. It leaves URLs and quotes unchanged, so the citation check still matches them.

The map links each label to its run, system and question, with a scrub count. It has to live outside the blinded folder, and judges must never see it. Both commands refuse to overwrite an existing output.

After grading, `python3 blind.py unblind --map <map.json> --scores <scores.csv> --out <graded.csv>` swaps each `label` for `run_id`, `system` and `question_id` and keeps the other columns. An unknown, blank, duplicate, or missing label stops it.
