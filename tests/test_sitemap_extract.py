import gzip
import textwrap

import pytest

from src.docs_pipeline import sitemap_extract as se


class DummyResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")


def make_index(child_urls):
    items = "".join([f"<sitemap><loc>{u}</loc></sitemap>" for u in child_urls])
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{items}</sitemapindex>".encode()


def make_urlset(urls_with_lastmod):
    items = "".join([f"<url><loc>{u}</loc><lastmod>{lm}</lastmod></url>" for u, lm in urls_with_lastmod])
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{items}</urlset>".encode()


def test_parse_index_and_urlset(monkeypatch):
    parent = "https://example.com/sitemap_index.xml"
    child = "https://example.com/sitemap_child.xml"
    urls = [("https://example.com/doc1","2023-01-01"),("https://example.com/doc2#frag","2023-01-02")]

    def fake_get(url, timeout=10):
        if url == parent:
            return DummyResponse(make_index([child]))
        elif url == child:
            return DummyResponse(make_urlset(urls))
        raise AssertionError("Unexpected URL: %s" % url)

    monkeypatch.setattr("requests.Session.get", lambda self, u, timeout=10: fake_get(u, timeout=timeout))

    starting = {"docs": parent}
    rows = list(se.extract_urls(starting))
    assert len(rows) == 2
    # check normalization (fragment removed)
    assert rows[0][2] == "https://example.com/doc1"
    assert rows[1][2] == "https://example.com/doc2"
    assert rows[1][3] == "2023-01-02"


def test_gz_support(monkeypatch):
    url = "https://example.com/sitemap.xml.gz"
    urls = [("https://example.com/g1","2023-02-02")]
    gz = gzip.compress(make_urlset(urls))

    def fake_get(u, timeout=10):
        assert u == url
        return DummyResponse(gz)

    monkeypatch.setattr("requests.Session.get", lambda self, u, timeout=10: fake_get(u, timeout=timeout))

    rows = list(se.extract_urls({"docs": url}))
    assert len(rows) == 1
    assert rows[0][2] == "https://example.com/g1"


def test_loop_prevention(monkeypatch):
    a = "https://a/s1.xml"
    b = "https://a/s2.xml"
    # s1 -> s2, s2 -> s1
    def fake_get(u, timeout=10):
        if u == a:
            return DummyResponse(make_index([b]))
        if u == b:
            return DummyResponse(make_index([a]))
        raise AssertionError("Unexpected %s" % u)

    monkeypatch.setattr("requests.Session.get", lambda self, u, timeout=10: fake_get(u, timeout=timeout))
    rows = list(se.extract_urls({"docs": a}, max_urls=100))
    # no URLs in urlsets, but should terminate without infinite loop
    assert rows == []


def test_batch_rows():
    items = [("s", "sm", f"doc{i}", None) for i in range(7)]
    batches = list(se.batch_rows(items, batch_size=3))
    assert len(batches) == 3
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3
    assert len(batches[2]) == 1
