# SPDX-License-Identifier: Apache-2.0
# Copyright Tony Burns
# cspell:ignore Straße STRASSE ＦＵＬＬ

"""Offline tests using injected fetches and an in-memory urllib transport."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from datetime import datetime, timedelta
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import HTTPHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import citecheck


BASE = "https://peer"
HTTP_BASE = "http://peer"
# 2000::/3 is global unicast; this address belongs to nobody.
PUBLIC = "2000::1"
NON_PUBLIC = {
    "loopback": "127.0.0.1",
    "link-local metadata": "169.254.169.254",
    "private 10/8": "10.1.2.3",
    "private 172.16/12": "172.16.0.9",
    "private 192.168/16": "192.168.1.1",
    "shared CGNAT 100.64/10": "100.100.0.1",
    "unspecified": "0.0.0.0",
    "IPv6 loopback": "::1",
    "IPv6 ULA": "fd00::1",
    "IPv6 link-local": "fe80::1",
    "IPv4-mapped loopback": "::ffff:127.0.0.1",
    "multicast": "ff02::1",
}


def resolver(table):
    def resolve(host, port):
        return table[host]
    return resolve


def answer_for(citations):
    return {
        "answer": "A fixture answer.",
        "confidence": "medium",
        "premise_ok": True,
        "claims": [{"text": "A fixture claim.", "citations": citations}],
        "tools_used": [],
    }


class FixtureTransport(HTTPHandler):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.requests = []
        self.streams = []

    def http_open(self, request):
        self.requests.append(request)
        fixture = self.routes[request.full_url]
        if isinstance(fixture, Exception):
            raise fixture
        code, headers, body = fixture
        message = Message()
        for key, value in headers.items():
            message[key] = value
        stream = io.BytesIO(body)
        self.streams.append(stream)
        response = addinfourl(stream, message, request.full_url, code)
        response.msg = "fixture response"
        return response


class MatchingTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(citecheck.match_quote("<p>Exact text.</p>", "Exact text."), "exact")

    def test_normalized(self):
        page = '<style>hidden words</style><p>“ＦＵＬＬ”&nbsp;— <b>Mixed</b>\n CASE</p><script>secret words</script>'
        self.assertEqual(citecheck.match_quote(page, '… "full" - mixed case ...'), "normalized")
        self.assertEqual(citecheck.match_quote(page, "HIDDEN WORDS"), "none")
        self.assertEqual(citecheck.match_quote(page, "SECRET WORDS"), "none")

    def test_inline_and_block_boundaries(self):
        self.assertEqual(citecheck.match_quote("<p>co<b>operate</b></p><p>now</p>", "COOPERATE NOW"), "normalized")

    def test_entities_and_unicode(self):
        self.assertEqual(citecheck.match_quote("<p>Cafe\u0301 &amp; ‘tea’ – Straße</p>", "CAFÉ & 'TEA' - STRASSE"), "normalized")

    def test_no_match_and_empty_quotes(self):
        for quote in ("missing", "", " \n", "…", "... ..."):
            with self.subTest(quote=quote):
                self.assertEqual(citecheck.match_quote("<p>Available text</p>", quote), "none")


class FetchTests(unittest.TestCase):
    def fetch(self, routes, path="/page"):
        transport = FixtureTransport(routes)
        opener = build_opener(ProxyHandler({}), citecheck.WebRedirectHandler(), transport)
        with patch.object(citecheck, "build_opener", return_value=opener), \
                patch.object(citecheck, "resolve", resolver(self.hosts)):
            result = citecheck.fetch_url(HTTP_BASE + path)
        return result, transport

    def setUp(self):
        self.hosts = {"peer": [PUBLIC]}

    def test_non_public_hosts_are_never_fetched(self):
        for label, address in NON_PUBLIC.items():
            with self.subTest(label), patch.object(citecheck, "build_opener") as opener, \
                    patch.object(citecheck, "resolve", resolver({"peer": [address]})):
                result = citecheck.fetch_url(HTTP_BASE + "/page")
                self.assertIn("non-public address", result.error)
                self.assertNotIn(address, result.error)
                self.assertIsNone(result.status)
                self.assertIsNone(result.body)
                opener.assert_not_called()

    def test_any_non_public_address_blocks_the_host(self):
        with patch.object(citecheck, "build_opener") as opener, \
                patch.object(citecheck, "resolve", resolver({"peer": [PUBLIC, "10.0.0.1"]})):
            result = citecheck.fetch_url(HTTP_BASE + "/page")
        self.assertIn("non-public address", result.error)
        opener.assert_not_called()

    def test_redirect_to_non_public_host_is_refused(self):
        self.hosts["internal"] = ["100.64.0.1"]
        result, transport = self.fetch({
            HTTP_BASE + "/page": (302, {"Location": "http://internal/secret"}, b""),
        })
        self.assertIn("non-public address", result.error)
        self.assertIsNone(result.body)
        self.assertEqual([r.full_url for r in transport.requests], [HTTP_BASE + "/page"])

    def test_pinned_connection_uses_the_checked_address(self):
        table = {"peer": [PUBLIC]}
        with patch.object(citecheck, "resolve", resolver(table)), \
                patch.object(citecheck.socket, "create_connection") as connect:
            connection = citecheck.PinnedHTTPSConnection("peer", 443, timeout=5)
            connection._create_connection(("peer", 443), 5, None)
        connect.assert_called_once_with((PUBLIC, 443), 5, None)

    def test_pinned_connection_rechecks_at_connect_time(self):
        # A rebinding resolver answers public for the pre-check and private at connect.
        with patch.object(citecheck, "resolve", resolver({"peer": ["127.0.0.1"]})), \
                patch.object(citecheck.socket, "create_connection") as connect:
            connection = citecheck.PinnedHTTPConnection("peer", 80, timeout=5)
            with self.assertRaises(citecheck.BlockedAddress):
                connection._create_connection(("peer", 80), 5, None)
        connect.assert_not_called()

    def test_redirect_and_request_settings(self):
        result, transport = self.fetch({
            HTTP_BASE + "/page": (302, {"Location": "/final", "Set-Cookie": "fixture=value"}, b""),
            HTTP_BASE + "/final": (200, {"Content-Type": "text/html; charset=iso-8859-1"}, b"caf\xe9"),
        })
        self.assertEqual(result.status, 200)
        self.assertEqual(result.final_url, HTTP_BASE + "/final")
        self.assertEqual(result.body, b"caf\xe9")
        self.assertEqual(result.charset, "iso-8859-1")
        self.assertIsNone(result.error)
        self.assertEqual(len(transport.requests), 2)
        for request in transport.requests:
            self.assertEqual(request.get_header("User-agent"), "evals-citecheck/0.1")
            self.assertEqual(request.timeout, 20)
            self.assertIsNone(request.get_header("Cookie"))
        self.assertTrue(all(stream.closed for stream in transport.streams))

    def test_404_body_is_preserved(self):
        result, _ = self.fetch({HTTP_BASE + "/page": (404, {}, b"Not found")})
        self.assertEqual(result.status, 404)
        self.assertEqual(result.body, b"Not found")
        self.assertEqual(result.error, "HTTP 404")

    def test_connection_errors(self):
        for error in (TimeoutError("timed out"), ConnectionError("connection failed")):
            with self.subTest(error=type(error).__name__):
                result, _ = self.fetch({HTTP_BASE + "/page": error})
                self.assertIsNone(result.status)
                self.assertIsNone(result.body)
                self.assertIn(str(error), result.error)

    def test_invalid_urls_never_open(self):
        for url in ("data:text/plain,text", "ftp://peer/page", "relative", "https:///page", "http://[", "http://peer:bad/"):
            with self.subTest(url=url), patch.object(citecheck, "build_opener") as opener:
                result = citecheck.fetch_url(url)
                self.assertIsNotNone(result.error)
                self.assertIsNone(result.status)
                opener.assert_not_called()

    def test_redirect_to_non_http_scheme_is_rejected(self):
        result, transport = self.fetch({
            HTTP_BASE + "/page": (302, {"Location": "ftp://peer/page"}, b""),
        })
        self.assertIn("only http and https", result.error)
        self.assertEqual(len(transport.requests), 1)

    def test_redirect_loop_is_an_error(self):
        result, _ = self.fetch({
            HTTP_BASE + "/page": (302, {"Location": "/page"}, b""),
        })
        self.assertEqual(result.status, 302)
        self.assertIsNotNone(result.error)

    def test_size_cap(self):
        for size in (citecheck.MAX_BYTES, citecheck.MAX_BYTES + 100):
            with self.subTest(size=size):
                result, _ = self.fetch({HTTP_BASE + "/page": (200, {}, b"x" * size)})
                self.assertEqual(len(result.body), citecheck.MAX_BYTES)
                self.assertEqual(result.status, 200)
                if size > citecheck.MAX_BYTES:
                    self.assertIn("archived prefix only", result.error)
                else:
                    self.assertIsNone(result.error)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "output"

    def write_answer(self, stem, answer):
        path = self.root / f"{stem}.json"
        path.write_text(json.dumps(answer), encoding="utf-8")
        return path

    def read_records(self, stem):
        return json.loads((self.out / f"{stem}.citations.json").read_text(encoding="utf-8"))

    def test_deduplication_schema_and_archive(self):
        calls = Counter()
        body = b"<p>Exact text.</p>"

        def fetch(url):
            calls[url] += 1
            return citecheck.FetchResult(status=200, final_url=BASE + "/final", body=body)

        citations = [
            {"url": BASE + "/one", "quote": "Exact text."},
            {"url": BASE + "/one", "quote": "EXACT TEXT."},
            {"url": BASE + "/two", "quote": "missing"},
        ]
        first = answer_for(citations)
        first["claims"].append({"text": "Second claim", "citations": citations[:1]})
        paths = [self.write_answer("first", first), self.write_answer("second", answer_for(citations))]
        with patch.object(citecheck, "ThreadPoolExecutor", wraps=ThreadPoolExecutor) as executor:
            self.assertEqual(citecheck.process_answers(paths, self.out, fetch), 0)
        executor.assert_called_once_with(max_workers=4)
        self.assertEqual(calls, {BASE + "/one": 1, BASE + "/two": 1})
        records = self.read_records("first")
        self.assertEqual([r["match"] for r in records], ["exact", "normalized", "none", "exact"])
        self.assertEqual([(r["claim_index"], r["citation_index"]) for r in records], [(0, 0), (0, 1), (0, 2), (1, 0)])
        self.assertEqual(len(self.read_records("second")), 3)
        for record in records:
            self.assertEqual(set(record), {
                "claim_index", "citation_index", "url", "status", "final_url", "error",
                "live", "quote_found", "match", "fetched_at", "sha256",
            })
            self.assertEqual(record["status"], 200)
            self.assertEqual(record["final_url"], BASE + "/final")
            self.assertIsNone(record["error"])
            self.assertIs(record["live"], True)
            self.assertIs(record["quote_found"], record["match"] != "none")
            self.assertTrue(record["fetched_at"].endswith("Z"))
            self.assertEqual(datetime.fromisoformat(record["fetched_at"]).utcoffset(), timedelta(0))
            self.assertEqual(record["sha256"], hashlib.sha256(body).hexdigest())
        bodies = list((self.out / "archive").iterdir())
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0].read_bytes(), body)

    def test_error_records_continue(self):
        urls = [BASE + "/missing", BASE + "/timeout", "data:text/plain,text", BASE + "/ok"]
        path = self.write_answer("errors", answer_for([{"url": url, "quote": "text"} for url in urls]))

        def fetch(url):
            if url.endswith("timeout"):
                raise TimeoutError("timed out")
            status = 404 if url.endswith("missing") else 200
            return citecheck.FetchResult(status=status, final_url=url, body=b"text")

        self.assertEqual(citecheck.process_answers([path], self.out, fetch), 0)
        records = self.read_records("errors")
        self.assertEqual([r["status"] for r in records], [404, None, None, 200])
        self.assertEqual([r["live"] for r in records], [False, False, False, True])
        for record in records[1:3]:
            self.assertIsNone(record["sha256"])
            self.assertIsNotNone(record["error"])
            self.assertFalse(record["quote_found"])
            self.assertEqual(record["match"], "none")

    def test_decoding_and_empty_body(self):
        path = self.write_answer("encoded", answer_for([
            {"url": BASE + "/latin", "quote": "café"},
            {"url": BASE + "/fallback", "quote": "café"},
            {"url": BASE + "/empty", "quote": ""},
        ]))

        def fetch(url):
            if url.endswith("empty"):
                return citecheck.FetchResult(status=204, final_url=url, body=b"")
            charset = "iso-8859-1" if url.endswith("latin") else "unknown-encoding"
            body = b"caf\xe9" if url.endswith("latin") else "café".encode()
            return citecheck.FetchResult(status=200, final_url=url, body=body, charset=charset)

        self.assertEqual(citecheck.process_answers([path], self.out, fetch), 0)
        records = self.read_records("encoded")
        self.assertEqual([r["match"] for r in records], ["exact", "exact", "none"])
        self.assertTrue(all(r["live"] for r in records))
        self.assertEqual(records[-1]["sha256"], hashlib.sha256(b"").hexdigest())

    def test_bad_inputs_exit_two_and_valid_files_still_processed(self):
        malformed = self.root / "malformed.json"
        malformed.write_text("{", encoding="utf-8")
        invalid = self.write_answer("invalid", {"claims": []})
        good = self.write_answer("good", answer_for([]))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(citecheck.main(["--out", str(self.out), str(malformed), str(invalid), str(good)]), 2)
        self.assertEqual(self.read_records("good"), [])
        self.assertFalse((self.out / "invalid.citations.json").exists())

    def test_schema_validation(self):
        for field, bad_value in (
            ("answer", None), ("confidence", "certain"), ("premise_ok", 1),
            ("tools_used", [1]), ("claims", {}), ("claims", [None]),
            ("claims", [{"text": "claim", "citations": [{"url": BASE, "quote": 1}]}]),
        ):
            with self.subTest(field=field, value=bad_value):
                answer = answer_for([])
                answer[field] = bad_value
                path = self.write_answer("invalid", answer)
                with self.assertRaises(ValueError):
                    citecheck.load_answer(path)

    def test_duplicate_stems_are_rejected(self):
        path = self.write_answer("same", answer_for([]))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(citecheck.process_answers([path, path], self.out), 2)
        self.assertEqual(self.read_records("same"), [])

    def test_bad_unicode_url_is_recorded(self):
        url = BASE + "/\ud800"
        path = self.write_answer("unicode", answer_for([{"url": url, "quote": "text"}]))

        def fetch(url):
            url.encode("utf-8")

        self.assertEqual(citecheck.process_answers([path], self.out, fetch), 0)
        record = self.read_records("unicode")[0]
        self.assertEqual(record["url"], url)
        self.assertIn("UnicodeEncodeError", record["error"])
        self.assertFalse(record["live"])

    def test_cli_success(self):
        path = self.write_answer("empty", answer_for([]))
        self.assertEqual(citecheck.main(["--out", str(self.out), str(path)]), 0)
        self.assertEqual(self.read_records("empty"), [])


if __name__ == "__main__":
    unittest.main()
