from types import SimpleNamespace

import pytest

from src.docs_pipeline import sitemap_extract as se


class DummyCursor:
    def __init__(self):
        self.executemany_calls = []

    def executemany(self, sql, params_list):
        self.executemany_calls.append((sql, params_list))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyConn:
    def __init__(self):
        self.cursor_obj = DummyCursor()

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


class DummyResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")


def make_urlset(urls_with_lastmod):
    items = "".join([f"<url><loc>{u}</loc><lastmod>{lm}</lastmod></url>" for u, lm in urls_with_lastmod])
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{items}</urlset>".encode()


def test_run_sitemap_extract_inserts(monkeypatch):
    # Setup sample sitemap content
    root_sitemap = "https://example.com/s1.xml"
    urls = [("https://example.com/doc1", None), ("https://example.com/doc2", "2024-01-02")]

    def fake_get(u, timeout=10):
        if u == root_sitemap:
            return DummyResponse(make_urlset(urls))
        raise AssertionError("unexpected URL %s" % u)

    monkeypatch.setattr("requests.Session.get", lambda self, u, timeout=10: fake_get(u, timeout=timeout))

    conn = DummyConn()
    sources = {"docs": root_sitemap}
    total = se.run_sitemap_extract("run-xyz", sources, conn=conn, batch_size=1)
    assert total == 2
    # Check that executemany was called (two batches because batch_size=1)
    assert len(conn.cursor_obj.executemany_calls) == 2
    sql0, params0 = conn.cursor_obj.executemany_calls[0]
    assert "INSERT INTO" in sql0
    assert params0[0][0] == "run-xyz"
    assert params0[0][2] == root_sitemap
    assert params0[0][3] == "https://example.com/doc1"


def test_run_sitemap_extract_with_error(monkeypatch):
    # if fetching fails, it should skip and return 0
    def fake_get(u, timeout=10):
        raise Exception("network")

    monkeypatch.setattr("requests.Session.get", lambda self, u, timeout=10: fake_get(u, timeout=timeout))
    conn = DummyConn()
    sources = {"docs": "https://example.com/nope.xml"}
    total = se.run_sitemap_extract("run-1", sources, conn=conn)
    assert total == 0
