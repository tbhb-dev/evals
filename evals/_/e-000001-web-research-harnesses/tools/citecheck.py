#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns
# cspell:ignore newurl figcaption charrefs
"""Check citation URL liveness and quoted text, preserving fetched evidence.

Whether a citation supports a claim is NOT this tool's job; an agent judge
evaluates that. Requires Python 3.12 or newer, with only the standard library.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_BYTES = 5_000_000
TIMEOUT = 20
USER_AGENT = "evals-citecheck/0.1"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FetchResult:
    status: int | None = None
    final_url: str | None = None
    error: str | None = None
    body: bytes | None = None
    charset: str = "utf-8"
    fetched_at: str = field(default_factory=utc_now)


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("only http and https URLs are allowed")
    if not parts.hostname:
        raise ValueError("URL must have a host")
    # Accessing port also validates malformed port numbers.
    _ = parts.port


class WebRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url):
    """Fetch one URL; retain at most MAX_BYTES, including for HTTP errors."""
    status = None
    final_url = url
    fetched_at = utc_now()
    try:
        validate_url(url)
        request = Request(url, headers={"User-Agent": USER_AGENT})
        # A fresh opener has no cookie processor or shared cookie state.
        opener = build_opener(WebRedirectHandler())
        try:
            response = opener.open(request, timeout=TIMEOUT)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.code
            final_url = response.geturl()
            validate_url(final_url)
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_BYTES)
            # One lookahead byte distinguishes a full body from a capped prefix.
            oversized = bool(response.read(1))
        error = f"HTTP {status}" if not 200 <= status < 300 else None
        if oversized:
            error = "; ".join(filter(None, [error, "body exceeds 5 MB; archived prefix only"]))
        return FetchResult(status, final_url, error, body, charset, fetched_at)
    except Exception as exc:
        return FetchResult(
            status=status,
            final_url=final_url,
            error=f"{type(exc).__name__}: {exc}",
            fetched_at=fetched_at,
        )


class PageText(HTMLParser):
    """Extract text while omitting scripts and styles."""

    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


PUNCTUATION = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
})


def normalize(text):
    parser = PageText()
    parser.feed(text)
    parser.close()
    text = html.unescape("".join(parser.parts))
    text = unicodedata.normalize("NFKC", text).casefold().translate(PUNCTUATION)
    return " ".join(text.split())


def match_quote(page, quote):
    if not quote.strip():
        return "none"
    if quote in page:
        return "exact"
    normalized_quote = normalize(quote)
    normalized_quote = re.sub(r"^(?:\.\.\.\s*)+|(?:\s*\.\.\.)+$", "", normalized_quote).strip()
    if normalized_quote and normalized_quote in normalize(page):
        return "normalized"
    return "none"


def load_answer(path):
    """Reject malformed JSON and answers that do not follow the answer schema."""
    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    answer = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
    if not isinstance(answer, dict):
        raise ValueError("answer must be an object")
    if not isinstance(answer.get("answer"), str):
        raise ValueError("answer must be a string")
    if answer.get("confidence") not in ("high", "medium", "low"):
        raise ValueError("invalid confidence")
    if type(answer.get("premise_ok")) is not bool:
        raise ValueError("premise_ok must be a boolean")
    tools = answer.get("tools_used")
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise ValueError("tools_used must be a list of strings")
    claims = answer.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            raise ValueError("each claim must have string text")
        citations = claim.get("citations")
        if not isinstance(citations, list):
            raise ValueError("citations must be a list")
        for citation in citations:
            if not isinstance(citation, dict) or not all(
                isinstance(citation.get(key), str) for key in ("url", "quote")
            ):
                raise ValueError("each citation must have a string URL and quote")
    return answer


def checked_fetch(url, fetch):
    try:
        validate_url(url)
        return fetch(url)
    except Exception as exc:
        return FetchResult(final_url=url, error=f"{type(exc).__name__}: {exc}")


def process_answers(inputs, out, fetch=fetch_url):
    """Process all valid inputs, sharing a URL cache across the invocation."""
    answers = []
    failed = False
    stems = set()
    for index, path in enumerate(inputs):
        try:
            if path.stem in stems:
                raise ValueError("input stems must be unique")
            stems.add(path.stem)
            answers.append((path.stem, load_answer(path)))
        except (OSError, ValueError, RecursionError) as exc:
            print(f"input {index + 1}: {type(exc).__name__}: invalid answer or duplicate stem", file=sys.stderr)
            failed = True

    urls = dict.fromkeys(
        citation["url"]
        for _, answer in answers
        for claim in answer["claims"]
        for citation in claim["citations"]
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = dict(zip(urls, executor.map(lambda url: checked_fetch(url, fetch), urls)))

    archive = out / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    cached = {}
    for url, result in results.items():
        digest = None
        page = ""
        if result.body is not None:
            digest = hashlib.sha256(result.body).hexdigest()
            body_path = archive / digest
            if not body_path.exists():
                body_path.write_bytes(result.body)
            try:
                page = result.body.decode(result.charset, errors="replace")
            except (LookupError, UnicodeError):
                page = result.body.decode("utf-8", errors="replace")
        cached[url] = (result, digest, page)

    for stem, answer in answers:
        records = []
        for claim_index, claim in enumerate(answer["claims"]):
            for citation_index, citation in enumerate(claim["citations"]):
                url = citation["url"]
                result, digest, page = cached[url]
                match = match_quote(page, citation["quote"])
                records.append({
                    "claim_index": claim_index,
                    "citation_index": citation_index,
                    "url": url,
                    "status": result.status,
                    "final_url": result.final_url,
                    "error": result.error,
                    "live": result.status is not None and 200 <= result.status < 300,
                    "quote_found": match != "none",
                    "match": match,
                    "fetched_at": result.fetched_at,
                    "sha256": digest,
                })
        (out / f"{stem}.citations.json").write_text(
            json.dumps(records, indent=2) + "\n", encoding="utf-8"
        )
    return 2 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("answers", nargs="+", type=Path)
    args = parser.parse_args(argv)
    return process_answers(args.answers, args.out)


if __name__ == "__main__":
    sys.exit(main())
