# Citation checker

`citecheck.py` fetches every URL that an answer cites and looks for the quoted text on that page. It follows HTTP and HTTPS redirects to record each final status code. Whether a source supports its claim is out of scope. A separate grading pass scores that.

The tool fetches each URL once per invocation, at most four at a time, with a 20-second timeout. It keeps at most 5,000,000 bytes of a body. For a larger page it records an error and matches quotes against that prefix. Each record includes the fetch time in Coordinated Universal Time and a hash of the body. The archive folder keeps each body once, under its hash, so a grader can repeat the check later. A failed body read still counts as live when the status was a success.

It tries an exact match first. If that fails, it strips markup, folds case, width and typographic quotes, collapses whitespace, and tries again.

Run `python3 citecheck.py --out results answer.json` with one or more answer files, each with a unique name. The tool writes `<input-stem>.citations.json` for each. It exits with code 2 when an input holds malformed JSON or breaks the answer schema, after it processes the valid inputs. Network and URL errors go into the records and never stop a run. It needs Python 3.12 or newer and nothing beyond the standard library.

To run the tests from the repository root, use `python3 -m unittest discover -s evals/_/e-000001-web-research-harnesses/tools -v`. They inject fetches and use an in-memory transport, so they work offline.
