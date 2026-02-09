import gzip
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from src.docs_pipeline import content_fetch as cf


class DummyResp:
    def __init__(self, status=200, content=b"ok", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class DummySession(requests.Session):
    def __init__(self, responses):
        super().__init__()
        self._it = iter(responses)
        self.last_requests = []

    def get(self, url, headers=None, timeout=10):
        self.last_requests.append((url, headers))
        try:
            return next(self._it)
        except StopIteration:
            raise Exception("no more responses")


def test_skip_based_on_lastmod():
    doc = {"DOCUMENT_URL": "https://example.com/d1", "LASTMOD": "2023-01-01T00:00:00"}
    content = {"LAST_SUCCESS_AT": "2023-02-01T00:00:00"}

    called = {}

    def write_cb(url, update):
        called[url] = update

    res = cf.fetch_and_process(DummySession([]), doc, content, write_cb)
    assert res["status"] == "SKIPPED"


def test_304_updates_status(monkeypatch):
    doc = {"DOCUMENT_URL": "https://example.com/d1", "LASTMOD": None}
    content = {"ETAG": '"abc"', "LAST_SUCCESS_AT": None}

    resp = DummyResp(status=304, content=b"", headers={})
    sess = DummySession([resp])

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    res = cf.fetch_and_process(sess, doc, content, write_cb)
    assert res["status"] == "NOT_MODIFIED"
    assert updates[doc["DOCUMENT_URL"]]["LAST_FETCH_STATUS"] == "NOT_MODIFIED"


def test_hash_compare_no_change(monkeypatch):
    content_bytes = b"same"
    h = cf.compute_hash(content_bytes)

    doc = {"DOCUMENT_URL": "https://example.com/d1", "LASTMOD": None}
    content = {"CONTENT_HASH": h, "LAST_SUCCESS_AT": None}

    resp = DummyResp(status=200, content=content_bytes, headers={})
    sess = DummySession([resp])

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    res = cf.fetch_and_process(sess, doc, content, write_cb)
    assert res["status"] == "NOT_MODIFIED"
    assert updates[doc["DOCUMENT_URL"]]["LAST_FETCH_STATUS"] == "NOT_MODIFIED"


def test_successful_fetch_updates_content():
    content_bytes = b"new content"
    resp = DummyResp(status=200, content=content_bytes, headers={"Content-Type": "text/html; charset=utf-8"})
    sess = DummySession([resp])

    doc = {"DOCUMENT_URL": "https://example.com/d2", "LASTMOD": None}
    content = None

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    res = cf.fetch_and_process(sess, doc, content, write_cb)
    assert res["status"] == "SUCCESS"
    assert updates[doc["DOCUMENT_URL"]]["CONTENT_HASH"] == cf.compute_hash(content_bytes)
    assert updates[doc["DOCUMENT_URL"]]["LAST_FETCH_STATUS"] == "SUCCESS"


def test_transient_retries_then_success(monkeypatch):
    # Two failures then a success
    r1 = DummyResp(status=500, content=b"err")
    r2 = DummyResp(status=500, content=b"err")
    r3 = DummyResp(status=200, content=b"ok")
    sess = DummySession([r1, r2, r3])

    doc = {"DOCUMENT_URL": "https://example.com/d3", "LASTMOD": None}
    content = None

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    res = cf.fetch_and_process(sess, doc, content, write_cb)
    assert res["status"] == "SUCCESS"
    assert updates[doc["DOCUMENT_URL"]]["LAST_FETCH_STATUS"] == "SUCCESS"


def test_failing_after_retries(monkeypatch):
    # All failures
    r1 = DummyResp(status=500, content=b"err")
    r2 = DummyResp(status=500, content=b"err")
    r3 = DummyResp(status=500, content=b"err")
    sess = DummySession([r1, r2, r3])

    doc = {"DOCUMENT_URL": "https://example.com/d4", "LASTMOD": None}
    content = None

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    res = cf.fetch_and_process(sess, doc, content, write_cb, settings={"retries": 2})
    assert res["status"] == "FAILED"
    assert updates[doc["DOCUMENT_URL"]]["LAST_FETCH_STATUS"] == "FAILED"
    assert updates[doc["DOCUMENT_URL"]]["CONSECUTIVE_FAILURES"] >= 1
