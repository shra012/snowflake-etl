import time

from src.docs_pipeline.content_fetch import fetch_and_process, compute_hash


class DummyResp:
    def __init__(self, status=200, content=b"ok", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class DummySession:
    def __init__(self, responses):
        self._it = iter(responses)

    def get(self, url, headers=None, timeout=10):
        try:
            return next(self._it)
        except StopIteration:
            raise Exception("no more responses")


def test_per_host_delay_enforced():
    # Two successful fetches should incur at least per_host_delay each
    resp1 = DummyResp(status=200, content=b"a")
    resp2 = DummyResp(status=200, content=b"b")
    sess = DummySession([resp1, resp2])

    updates = {}

    def write_cb(url, update):
        updates[url] = update

    doc = {"DOCUMENT_URL": "https://example.com/d1", "LASTMOD": None}
    # run twice and measure duration
    start = time.time()
    r1 = fetch_and_process(sess, doc, None, write_cb, settings={"per_host_delay": 0.02})
    r2 = fetch_and_process(sess, doc, None, write_cb, settings={"per_host_delay": 0.02})
    duration = time.time() - start
    assert duration >= 0.02, "per_host_delay not observed"
    assert r1["status"] == "SUCCESS"
    assert r2["status"] == "SUCCESS"
