"""Document content fetcher (Task 3).

Features:
- Throttling (simple per-host delay)
- Retries with exponential backoff and respect for Retry-After
- Conditional GET using ETag / If-Modified-Since
- NOT_MODIFIED handling (304)
- Hash compare fallback
- Write-back via provided `write_callback` (for testability)

Public API:
- fetch_url(session, url, headers) -> requests.Response
- compute_hash(bytes) -> hex string
- should_fetch_based_on_lastmod(doc_lastmod, content_last_success_at) -> bool
- fetch_and_process(session, doc_entry, content_entry, write_callback, settings) -> result dict
- run_content_fetch(conn, batch_size, settings)

Note: `doc_entry` is a dict-like with at least keys: DOCUMENT_URL, LASTMOD
`content_entry` is dict-like with keys from DOCUMENT_CONTENT table when present.
`write_callback` receives (document_url, update_dict) and is responsible for writing to DB.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import requests

from docs_pipeline.config import tbl

DEFAULT_PER_HOST_DELAY = 0.1  # seconds
DEFAULT_RETRIES = 3


def compute_hash(content: bytes) -> str:
    h = hashlib.sha256()
    h.update(content)
    return h.hexdigest()


def should_fetch_based_on_lastmod(doc_lastmod: Optional[str], last_success_at: Optional[str]) -> bool:
    if not doc_lastmod or not last_success_at:
        return True
    try:
        # Compare ISO timestamps or dates; both stored as strings; parse conservatively
        doc_ts = datetime.fromisoformat(doc_lastmod)
        last_success_ts = datetime.fromisoformat(last_success_at)
        return doc_ts > last_success_ts
    except Exception:
        # On parse errors, fall back to fetching
        return True


def fetch_url(session: requests.Session, url: str, headers: Dict[str, str], timeout: int = 10) -> requests.Response:
    return session.get(url, headers=headers, timeout=timeout)


def _respect_retry_after(resp: requests.Response) -> Optional[float]:
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        # could be HTTP date or seconds; try int first
        seconds = int(ra)
        return float(seconds)
    except Exception:
        try:
            parsed = requests.utils.parse_header_links(ra)
        except Exception:
            return None
    return None


def fetch_and_process(
    session: requests.Session,
    doc_entry: Dict[str, Any],
    content_entry: Optional[Dict[str, Any]],
    write_callback: Callable[[str, Dict[str, Any]], None],
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch a single URL with conditional logic and call `write_callback` with updates.

    - `doc_entry` must contain: DOCUMENT_URL (str), LASTMOD (optional str)
    - `content_entry` may be None or contain previous metadata: ETAG, HTTP_LAST_MODIFIED, CONTENT_HASH, LAST_SUCCESS_AT
    - `write_callback(document_url, update_dict)` will be called with update/insert data

    Returns a dict result describing outcome (status: SKIPPED|NOT_MODIFIED|SUCCESS|FAILED)
    """
    settings = settings or {}
    per_host_delay = settings.get("per_host_delay", DEFAULT_PER_HOST_DELAY)
    retries = settings.get("retries", DEFAULT_RETRIES)

    url = doc_entry["DOCUMENT_URL"]
    lastmod = doc_entry.get("LASTMOD")

    # Short-circuit based on LASTMOD vs LAST_SUCCESS_AT
    prev_last_success = content_entry.get("LAST_SUCCESS_AT") if content_entry else None
    if not should_fetch_based_on_lastmod(lastmod, prev_last_success):
        # Skip network call and return SKIPPED
        return {"status": "SKIPPED", "reason": "lastmod_not_newer"}

    headers = {}
    if content_entry:
        etag = content_entry.get("ETAG")
        http_last_mod = content_entry.get("HTTP_LAST_MODIFIED")
        if etag:
            headers["If-None-Match"] = etag
        elif http_last_mod:
            headers["If-Modified-Since"] = http_last_mod

    attempt = 0
    last_error = None
    while attempt <= retries:
        attempt += 1
        try:
            resp = fetch_url(session, url, headers)
            status = resp.status_code

            if status == 304:
                # Not modified; update LAST_FETCH_* and keep content as is
                update = {
                    "LAST_FETCH_AT": datetime.now(timezone.utc).isoformat(),
                    "LAST_FETCH_STATUS": "NOT_MODIFIED",
                    "LAST_HTTP_STATUS": 304,
                    "LAST_ERROR": None,
                }
                write_callback(url, update)
                return {"status": "NOT_MODIFIED"}

            if 200 <= status < 300:
                content_bytes = resp.content
                content_hash = compute_hash(content_bytes)
                content_length = len(content_bytes)
                content_type = resp.headers.get("Content-Type")
                etag = resp.headers.get("ETag")
                http_last_mod = resp.headers.get("Last-Modified")

                # Hash compare fallback
                prev_hash = content_entry.get("CONTENT_HASH") if content_entry else None
                if prev_hash and prev_hash == content_hash:
                    update = {
                        "LAST_FETCH_AT": datetime.now(timezone.utc).isoformat(),
                        "LAST_FETCH_STATUS": "NOT_MODIFIED",
                        "LAST_HTTP_STATUS": status,
                        "LAST_ERROR": None,
                    }
                    write_callback(url, update)
                    return {"status": "NOT_MODIFIED", "by": "hash"}

                # Success: store content and metadata
                update = {
                    "CONTENT_TEXT": content_bytes.decode("utf-8", errors="replace"),
                    "CONTENT_HASH": content_hash,
                    "CONTENT_LENGTH_BYTES": content_length,
                    "CONTENT_TYPE": content_type,
                    "ETAG": etag,
                    "HTTP_LAST_MODIFIED": http_last_mod,
                    "LAST_FETCH_AT": datetime.now(timezone.utc).isoformat(),
                    "LAST_FETCH_STATUS": "SUCCESS",
                    "LAST_HTTP_STATUS": status,
                    "LAST_ERROR": None,
                    "LAST_SUCCESS_AT": datetime.now(timezone.utc).isoformat(),
                    "CONSECUTIVE_FAILURES": 0,
                }
                write_callback(url, update)
                time.sleep(per_host_delay)
                return {"status": "SUCCESS"}

            # 4xx/5xx errors
            retry_after = _respect_retry_after(resp)
            last_error = f"HTTP {status}"
            if 500 <= status < 600 or status == 429:
                if retry_after:
                    time.sleep(retry_after)
                else:
                    time.sleep(2 ** attempt * 0.1)
                continue
            else:
                # Non-retryable client error
                update = {
                    "LAST_FETCH_AT": datetime.now(timezone.utc).isoformat(),
                    "LAST_FETCH_STATUS": "FAILED",
                    "LAST_HTTP_STATUS": status,
                    "LAST_ERROR": f"HTTP {status}",
                    "CONSECUTIVE_FAILURES": (content_entry.get("CONSECUTIVE_FAILURES", 0) + 1) if content_entry else 1,
                }
                write_callback(url, update)
                return {"status": "FAILED", "code": status}
        except Exception as exc:
            last_error = str(exc)
            # backoff
            time.sleep(2 ** attempt * 0.1)
            continue

    # If we reach here, mark as failed
    update = {
        "LAST_FETCH_AT": datetime.now(timezone.utc).isoformat(),
        "LAST_FETCH_STATUS": "FAILED",
        "LAST_HTTP_STATUS": None,
        "LAST_ERROR": last_error,
        "CONSECUTIVE_FAILURES": (content_entry.get("CONSECUTIVE_FAILURES", 0) + 1) if content_entry else 1,
    }
    write_callback(url, update)
    return {"status": "FAILED", "error": last_error}


def run_content_fetch(conn, batch_size: int = 100, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Driver to fetch content for URLs in DOCS_MASTER which need fetching.

    Strategy:
    - Select candidate URLs from DOCS_MASTER joined to DOCUMENT_CONTENT (left join)
    - For each URL, decide whether to fetch using `should_fetch_based_on_lastmod`
    - Process in batches and call DB to update DOCUMENT_CONTENT (using simple MERGE pattern)

    Returns a summary dict.
    """
    settings = settings or {}
    session = requests.Session()

    # Build select query: In production, you'd limit by LAST_SUCCESS_AT/Staleness strategy. For now select all (support 'max_docs' via settings).
    with conn.cursor() as cur:
        cur.execute(f"SELECT DOCUMENT_URL, LASTMOD FROM {tbl('DOCS_MASTER')}")
        rows = cur.fetchall()

    # Optional: limit the number of documents processed for smoke runs
    max_docs = settings.get("max_docs") if isinstance(settings, dict) else None
    if max_docs is not None:
        try:
            max_docs = int(max_docs)
            rows = rows[:max_docs]
        except Exception:
            pass

    total = 0
    successes = 0
    failures = 0

    def write_cb(doc_url: str, update: Dict[str, Any]):
        # Merge-like upsert into DOCUMENT_CONTENT
        columns = ", ".join(update.keys())
        placeholders = ", ".join(["%s"] * len(update))
        sql = f"MERGE INTO {tbl('DOCUMENT_CONTENT')} t USING (SELECT %s as DOCUMENT_URL) s ON t.DOCUMENT_URL = s.DOCUMENT_URL WHEN MATCHED THEN UPDATE SET " + ", ".join([f"{k} = %s" for k in update.keys()]) + " WHEN NOT MATCHED THEN INSERT (DOCUMENT_URL, " + columns + ") VALUES (%s, " + placeholders + ")"
        # Values: DOCUMENT_URL for using select, then update values twice (once for update set, once for insert)
        vals = [doc_url] + list(update.values()) + [doc_url] + list(update.values())
        with conn.cursor() as cur:
            cur.execute(sql, vals)

    from datetime import datetime
    from .observability import record_pipeline_metrics, raise_alert

    started = datetime.utcnow()
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        for doc_url, lastmod in batch:
            total += 1
            # fetch previous content row
            with conn.cursor() as cur:
                cur.execute(f"SELECT CONTENT_HASH, ETAG, HTTP_LAST_MODIFIED, LAST_SUCCESS_AT, CONSECUTIVE_FAILURES FROM {tbl('DOCUMENT_CONTENT')} WHERE DOCUMENT_URL = %s", (doc_url,))
                prev = cur.fetchone()
                content_entry = None
                if prev:
                    content_entry = {
                        "CONTENT_HASH": prev[0],
                        "ETAG": prev[1],
                        "HTTP_LAST_MODIFIED": prev[2],
                        "LAST_SUCCESS_AT": prev[3],
                        "CONSECUTIVE_FAILURES": prev[4],
                    }
            result = fetch_and_process(session, {"DOCUMENT_URL": doc_url, "LASTMOD": lastmod}, content_entry, write_cb, settings)
            if result.get("status") == "SUCCESS":
                successes += 1
            elif result.get("status") == "FAILED":
                failures += 1

    # record metrics and raise alerts if failure rate too high
    ended = datetime.utcnow()
    try:
        record_pipeline_metrics(conn, 'content_fetch_run', 'content_pipeline', 'fetch', started, ended, rows_input=total, rows_output=successes, success_count=successes, failure_count=failures)
        # threshold example: failure rate > 20% -> critical
        failure_rate = (failures / total) if total > 0 else 0.0
        if failure_rate > 0.2:
            raise_alert(conn, f"CONTENT_FETCH_FAILURES_{int(time.time())}", None, 'failure_rate', 'CRITICAL', f'Content fetch failure rate {failure_rate:.2%}', metric_name='failure_rate', metric_value=failure_rate, threshold=0.2)
        elif failure_rate > 0.05:
            raise_alert(conn, f"CONTENT_FETCH_FAILURES_{int(time.time())}", None, 'failure_rate', 'WARN', f'Content fetch failure rate {failure_rate:.2%}', metric_name='failure_rate', metric_value=failure_rate, threshold=0.05)
    except Exception:
        pass

    return {"total": total, "successes": successes, "failures": failures}


def run_content_fetch_parallel(conn, batch_size: int = 100, settings: Optional[Dict[str, Any]] = None, max_workers: int = 10) -> Dict[str, Any]:
    """Parallelized driver to fetch content for URLs in DOCS_MASTER.

    Uses ThreadPoolExecutor for concurrent HTTP fetching while keeping DB writes thread-safe.
    
    Args:
        conn: Snowflake connection
        batch_size: Number of URLs to process per batch for progress reporting
        settings: Optional settings dict (supports 'max_docs', 'per_host_delay', 'retries')
        max_workers: Number of parallel worker threads (default 10)

    Returns a summary dict with total, successes, failures, and skipped counts.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    from datetime import datetime
    from .observability import record_pipeline_metrics, raise_alert

    settings = settings or {}

    # Fetch all candidate URLs
    with conn.cursor() as cur:
        cur.execute(f"SELECT DOCUMENT_URL, LASTMOD FROM {tbl('DOCS_MASTER')}")
        rows = cur.fetchall()

    # Optional: limit the number of documents processed
    max_docs = settings.get("max_docs")
    if max_docs is not None:
        try:
            rows = rows[:int(max_docs)]
        except Exception:
            pass

    # Pre-fetch all existing content entries in one query for efficiency
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT DOCUMENT_URL, CONTENT_HASH, ETAG, HTTP_LAST_MODIFIED, LAST_SUCCESS_AT, CONSECUTIVE_FAILURES 
            FROM {tbl('DOCUMENT_CONTENT')}
        """)
        content_rows = cur.fetchall()
    
    content_cache = {}
    for row in content_rows:
        content_cache[row[0]] = {
            "CONTENT_HASH": row[1],
            "ETAG": row[2],
            "HTTP_LAST_MODIFIED": row[3],
            "LAST_SUCCESS_AT": row[4],
            "CONSECUTIVE_FAILURES": row[5],
        }

    # Thread-safe counters
    counters = {"total": 0, "successes": 0, "failures": 0, "skipped": 0}
    counters_lock = Lock()
    db_lock = Lock()

    def write_cb_threadsafe(doc_url: str, update: Dict[str, Any]):
        """Thread-safe DB write callback."""
        columns = ", ".join(update.keys())
        placeholders = ", ".join(["%s"] * len(update))
        sql = f"MERGE INTO {tbl('DOCUMENT_CONTENT')} t USING (SELECT %s as DOCUMENT_URL) s ON t.DOCUMENT_URL = s.DOCUMENT_URL WHEN MATCHED THEN UPDATE SET " + ", ".join([f"{k} = %s" for k in update.keys()]) + " WHEN NOT MATCHED THEN INSERT (DOCUMENT_URL, " + columns + ") VALUES (%s, " + placeholders + ")"
        vals = [doc_url] + list(update.values()) + [doc_url] + list(update.values())
        with db_lock:
            with conn.cursor() as cur:
                cur.execute(sql, vals)

    def process_url(doc_url: str, lastmod: Optional[str], session: requests.Session) -> str:
        """Process a single URL and return status."""
        content_entry = content_cache.get(doc_url)
        result = fetch_and_process(
            session, 
            {"DOCUMENT_URL": doc_url, "LASTMOD": lastmod}, 
            content_entry, 
            write_cb_threadsafe, 
            settings
        )
        return result.get("status", "UNKNOWN")

    started = datetime.utcnow()
    
    # Process URLs in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Each thread gets its own session for connection pooling
        import threading
        thread_sessions = threading.local()
        
        def get_session():
            if not hasattr(thread_sessions, 'session'):
                thread_sessions.session = requests.Session()
            return thread_sessions.session

        def worker(doc_url: str, lastmod: Optional[str]) -> str:
            session = get_session()
            return process_url(doc_url, lastmod, session)

        futures = {executor.submit(worker, doc_url, lastmod): doc_url for doc_url, lastmod in rows}
        
        processed = 0
        for future in as_completed(futures):
            doc_url = futures[future]
            try:
                status = future.result()
                with counters_lock:
                    counters["total"] += 1
                    if status == "SUCCESS":
                        counters["successes"] += 1
                    elif status == "FAILED":
                        counters["failures"] += 1
                    elif status in ("SKIPPED", "NOT_MODIFIED"):
                        counters["skipped"] += 1
            except Exception as e:
                with counters_lock:
                    counters["total"] += 1
                    counters["failures"] += 1
            
            processed += 1
            if processed % batch_size == 0:
                print(f"Progress: {processed}/{len(rows)} ({100*processed/len(rows):.1f}%)")

    ended = datetime.utcnow()
    
    # Record metrics
    try:
        record_pipeline_metrics(
            conn, 'content_fetch_parallel', 'content_pipeline', 'fetch', 
            started, ended, 
            rows_input=counters["total"], 
            rows_output=counters["successes"], 
            success_count=counters["successes"], 
            failure_count=counters["failures"],
            skipped_count=counters["skipped"]
        )
        
        failure_rate = (counters["failures"] / counters["total"]) if counters["total"] > 0 else 0.0
        if failure_rate > 0.2:
            raise_alert(conn, f"CONTENT_FETCH_FAILURES_{int(time.time())}", None, 'failure_rate', 'CRITICAL', 
                       f'Content fetch failure rate {failure_rate:.2%}', metric_name='failure_rate', 
                       metric_value=failure_rate, threshold=0.2)
        elif failure_rate > 0.05:
            raise_alert(conn, f"CONTENT_FETCH_FAILURES_{int(time.time())}", None, 'failure_rate', 'WARN', 
                       f'Content fetch failure rate {failure_rate:.2%}', metric_name='failure_rate', 
                       metric_value=failure_rate, threshold=0.05)
    except Exception:
        pass

    return {
        "total": counters["total"], 
        "successes": counters["successes"], 
        "failures": counters["failures"],
        "skipped": counters["skipped"],
        "duration_seconds": (ended - started).total_seconds()
    }
