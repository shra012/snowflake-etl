"""Sitemap extraction utilities (Task 1).

Features implemented:
- Parse sitemapindex vs urlset
- Recursive crawling of nested sitemaps with visited set
- Support for gzipped sitemaps (.xml.gz or gz content)
- URL normalization (strip fragments, trim whitespace)
- Batching helper to yield rows for insertion to staging

Public functions:
- extract_urls(starting: dict[str, str], max_urls=None)
- batch_rows(iterator, batch_size)

Note: DB write helpers are intentionally separate so tests can focus on parsing + crawling.
"""
from __future__ import annotations

import gzip
import io
import re
from typing import Iterable, Iterator, List, Optional, Tuple

import requests
import xml.etree.ElementTree as ET

from .config import tbl

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _normalize_url(url: str) -> str:
    url = url.strip()
    # Remove fragment
    url = url.split("#", 1)[0]
    return url


def _is_gzip_content(content: bytes) -> bool:
    return bool(content[:2] == b"\x1f\x8b")


def _parse_sitemap(content: bytes) -> Tuple[str, List[Tuple[str, Optional[str]]]]:
    """Parse sitemap XML bytes and return (type, items).

    type is 'index' or 'urlset'.
    items is list of tuples: (loc, lastmod) where lastmod may be None.
    """
    # handle gzip
    if _is_gzip_content(content):
        content = gzip.decompress(content)

    root = ET.fromstring(content)
    tag = root.tag
    # strip namespace
    if tag.startswith("{"):
        ns, local = tag[1:].split("}")
        tag = local

    items: List[Tuple[str, Optional[str]]] = []

    if tag == "sitemapindex":
        for sm in root.findall(f".//{{{SITEMAP_NS}}}sitemap"):
            loc = sm.find(f"{{{SITEMAP_NS}}}loc")
            lastmod = sm.find(f"{{{SITEMAP_NS}}}lastmod")
            if loc is None or loc.text is None:
                continue
            items.append((_normalize_url(loc.text), lastmod.text.strip() if (lastmod is not None and lastmod.text) else None))
        return "index", items
    elif tag == "urlset":
        for url in root.findall(f".//{{{SITEMAP_NS}}}url"):
            loc = url.find(f"{{{SITEMAP_NS}}}loc")
            lastmod = url.find(f"{{{SITEMAP_NS}}}lastmod")
            if loc is None or loc.text is None:
                continue
            items.append((_normalize_url(loc.text), lastmod.text.strip() if (lastmod is not None and lastmod.text) else None))
        return "urlset", items
    else:
        raise ValueError("Unknown sitemap root element: %s" % tag)


def extract_urls(starting: dict, max_urls: Optional[int] = None, session: Optional[requests.Session] = None) -> Iterator[Tuple[str, str, str, Optional[str]]]:
    """Crawl sitemaps beginning from `starting` mapping of source_identifier->sitemap_url.

    Yields tuples: (run_id_placeholder, source_identifier, sitemap_url, document_url, lastmod)

    For Task 1 we return tuples: (source_identifier, sitemap_url, document_url, lastmod)
    """
    sess = session or requests.Session()
    visited: set = set()
    pending: List[Tuple[str, str]] = []  # list of (source_identifier, sitemap_url)

    for source_identifier, sitemap_url in starting.items():
        pending.append((source_identifier, sitemap_url))

    seen_docs = 0

    while pending:
        source_identifier, sitemap_url = pending.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        # fetch
        try:
            r = sess.get(sitemap_url, timeout=10)
            r.raise_for_status()
            content = r.content
        except Exception:
            # skip on error; production code should log/metric
            continue

        try:
            s_type, items = _parse_sitemap(content)
        except Exception:
            continue

        if s_type == "index":
            for loc, lastmod in items:
                if loc not in visited:
                    pending.append((source_identifier, loc))
        else:
            for loc, lastmod in items:
                yield (source_identifier, sitemap_url, loc, lastmod)
                seen_docs += 1
                if max_urls is not None and seen_docs >= max_urls:
                    return


def batch_rows(rows: Iterable[Tuple[str, str, str, Optional[str]]], batch_size: int = 500) -> Iterator[List[Tuple[str, str, str, Optional[str]]]]:
    buf: List[Tuple[str, str, str, Optional[str]]] = []
    for r in rows:
        buf.append(r)
        if len(buf) >= batch_size:
            yield buf
            buf = []
    if buf:
        yield buf


# Database helpers
def insert_sitemap_staging(conn, run_id: str, rows: List[Tuple[str, str, str, Optional[str]]]):
    """Insert a batch of sitemap staging rows into Snowflake.

    Uses `executemany` for batch insertion. Rows are tuples: (source_identifier, sitemap_url, document_url, lastmod)
    """
    if not rows:
        return 0
    sql = f"INSERT INTO {tbl('SITEMAP_STAGING')} (RUN_ID, SOURCE_IDENTIFIER, SITEMAP_URL, DOCUMENT_URL, LASTMOD) VALUES (%s, %s, %s, %s, %s)"
    params = [(run_id, src, sitemap, doc, lastmod) for (src, sitemap, doc, lastmod) in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    return len(params)


def run_sitemap_extract(run_id: str, sources: dict, conn=None, session: Optional[requests.Session] = None, batch_size: int = 500, max_urls: Optional[int] = None) -> int:
    """Extract sitemaps from `sources` and insert into the staging table.

    sources: mapping of source_identifier -> sitemap_url

    Optional `max_urls` limits the number of document URLs extracted (useful for smoke runs).

    Returns total inserted rows and records metrics.
    """
    from datetime import datetime
    from .observability import record_pipeline_metrics

    started = datetime.utcnow()

    # create a connection if not provided
    created_conn = False
    if conn is None:
        from .snowflake import get_connection

        conn = get_connection()
        created_conn = True

    total = 0
    success = 0
    failure = 0
    try:
        rows_iter = extract_urls(sources, max_urls=max_urls, session=session)
        for batch in batch_rows(rows_iter, batch_size=batch_size):
            try:
                inserted = insert_sitemap_staging(conn, run_id, batch)
                total += inserted
                success += inserted
            except Exception:
                failure += 1
    finally:
        ended = datetime.utcnow()
        try:
            record_pipeline_metrics(conn, run_id, 'sitemap_extract', 'extract', started, ended, rows_input=None, rows_output=total, success_count=success, failure_count=failure)
        except Exception:
            pass
        if created_conn:
            try:
                conn.close()
            except Exception:
                pass
    return total
