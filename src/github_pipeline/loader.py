"""Load raw GitHub data into Snowflake with MERGE (upsert) semantics.

Each loader function accepts a Snowflake connection and a list of raw API
response dicts, extracts the relevant fields, and MERGEs into the
corresponding table. This ensures idempotent loads and supports resume.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import json

from src.docs_pipeline.config import tbl


# ── Resume helpers ──────────────────────────────────────────────────────────

def get_resume_point(conn, table_suffix: str, date_column: str) -> Optional[str]:
    """Query MAX of a date column to find where to resume ingestion.

    Args:
        conn: Snowflake connection.
        table_suffix: e.g. ``'GH_RAW_COMMITS'``.
        date_column: e.g. ``'COMMITTED_DATE'``.

    Returns:
        ISO 8601 timestamp string, or ``None`` if the table is empty.
    """
    table_name = tbl(table_suffix)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX({date_column}) FROM {table_name}")
            row = cur.fetchone()
            if row and row[0]:
                return row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0])
    except Exception as e:
        print(f"  Resume check for {table_name}: {e} (treating as fresh start)")
    return None


def get_loaded_count(conn, table_suffix: str) -> int:
    """Return the current row count for a raw table."""
    table_name = tbl(table_suffix)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


# ── Loaders ─────────────────────────────────────────────────────────────────

def _merge_batch(conn, table_name: str, columns: List[str], key_columns: List[str],
                 rows: List[tuple], variant_columns: Optional[set] = None) -> int:
    """Generic MERGE INTO using a VALUES staging approach.

    Args:
        variant_columns: Set of column names that should be cast via
                         ``PARSE_JSON()`` (for VARIANT columns).

    Returns the number of rows merged.
    """
    if not rows:
        return 0

    variant_columns = variant_columns or set()

    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    key_match = " AND ".join([f"target.{k} = source.{k}" for k in key_columns])
    update_set = ", ".join(
        [f"target.{c} = source.{c}" for c in columns if c not in key_columns]
    )
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join([f"source.{c}" for c in columns])

    # Build the source query from VALUES
    value_rows = []
    params = []
    for row in rows:
        value_rows.append(f"({placeholders})")
        params.extend(row)

    values_sql = ", ".join(value_rows)

    # Wrap VARIANT columns with PARSE_JSON() in the SELECT aliases
    col_aliases = ", ".join(
        f"PARSE_JSON(column{i+1}) AS {c}" if c in variant_columns
        else f"column{i+1} AS {c}"
        for i, c in enumerate(columns)
    )

    sql = f"""
    MERGE INTO {table_name} AS target
    USING (
        SELECT {col_aliases}
        FROM VALUES {values_sql}
    ) AS source
    ON {key_match}
    WHEN MATCHED THEN UPDATE SET {update_set}
    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return len(rows)


def load_commits(conn, data: List[dict]) -> int:
    """Load commit data into GH_RAW_COMMITS. Returns rows merged."""
    if not data:
        return 0
    table_name = tbl("GH_RAW_COMMITS")
    columns = ["SHA", "AUTHOR_NAME", "AUTHOR_LOGIN", "COMMITTED_DATE", "MESSAGE", "RAW_JSON"]
    key_columns = ["SHA"]

    rows = []
    for item in data:
        commit = item.get("commit", {})
        author = commit.get("author", {})
        user = item.get("author") or {}
        rows.append((
            item.get("sha", ""),
            author.get("name", ""),
            user.get("login", "") if isinstance(user, dict) else "",
            author.get("date", None),
            (commit.get("message", "") or "")[:5000],
            json.dumps(item),
        ))

    # Process in batches of 500 to stay within Snowflake limits
    total = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        total += _merge_batch(conn, table_name, columns, key_columns, batch, variant_columns={"RAW_JSON"})

    print(f"  Loaded {total} commits into {table_name}")
    return total


def load_pulls(conn, data: List[dict]) -> int:
    """Load pull request data into GH_RAW_PULLS. Returns rows merged."""
    if not data:
        return 0
    table_name = tbl("GH_RAW_PULLS")
    columns = ["NUMBER", "AUTHOR_LOGIN", "STATE", "TITLE", "UPDATED_AT", "CREATED_AT", "RAW_JSON"]
    key_columns = ["NUMBER"]

    rows = []
    for item in data:
        user = item.get("user") or {}
        rows.append((
            item.get("number", 0),
            user.get("login", "") if isinstance(user, dict) else "",
            item.get("state", ""),
            (item.get("title", "") or "")[:2000],
            item.get("updated_at"),
            item.get("created_at"),
            json.dumps(item),
        ))

    total = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        total += _merge_batch(conn, table_name, columns, key_columns, rows[i:i + batch_size], variant_columns={"RAW_JSON"})

    print(f"  Loaded {total} pulls into {table_name}")
    return total


def load_pr_comments(conn, data: List[dict]) -> int:
    """Load PR comment data into GH_RAW_PR_COMMENTS. Returns rows merged."""
    if not data:
        return 0
    table_name = tbl("GH_RAW_PR_COMMENTS")
    columns = ["ID", "AUTHOR_LOGIN", "PULL_REQUEST_URL", "UPDATED_AT", "CREATED_AT", "BODY", "RAW_JSON"]
    key_columns = ["ID"]

    rows = []
    for item in data:
        user = item.get("user") or {}
        rows.append((
            item.get("id", 0),
            user.get("login", "") if isinstance(user, dict) else "",
            item.get("pull_request_url", ""),
            item.get("updated_at"),
            item.get("created_at"),
            (item.get("body", "") or "")[:10000],
            json.dumps(item),
        ))

    total = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        total += _merge_batch(conn, table_name, columns, key_columns, rows[i:i + batch_size], variant_columns={"RAW_JSON"})

    print(f"  Loaded {total} PR comments into {table_name}")
    return total


def load_issues(conn, data: List[dict]) -> int:
    """Load issue data into GH_RAW_ISSUES. Returns rows merged."""
    if not data:
        return 0
    table_name = tbl("GH_RAW_ISSUES")
    columns = ["ID", "AUTHOR_LOGIN", "STATE", "TITLE", "UPDATED_AT", "CREATED_AT", "RAW_JSON"]
    key_columns = ["ID"]

    rows = []
    for item in data:
        user = item.get("user") or {}
        rows.append((
            item.get("id", 0),
            user.get("login", "") if isinstance(user, dict) else "",
            item.get("state", ""),
            (item.get("title", "") or "")[:2000],
            item.get("updated_at"),
            item.get("created_at"),
            json.dumps(item),
        ))

    total = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        total += _merge_batch(conn, table_name, columns, key_columns, rows[i:i + batch_size], variant_columns={"RAW_JSON"})

    print(f"  Loaded {total} issues into {table_name}")
    return total


def load_reviews(conn, data: List[dict], pull_numbers_map: dict = None) -> int:
    """Load review data into GH_RAW_REVIEWS. Returns rows merged.

    Args:
        conn: Snowflake connection.
        data: List of review dicts. Each should have an ``id`` and
              the pull number should be derivable from the ``pull_request_url``
              or provided via ``pull_numbers_map``.
        pull_numbers_map: Optional mapping of review id -> pull number.
    """
    if not data:
        return 0
    table_name = tbl("GH_RAW_REVIEWS")
    columns = ["ID", "PULL_NUMBER", "AUTHOR_LOGIN", "STATE", "SUBMITTED_AT", "RAW_JSON"]
    key_columns = ["ID", "PULL_NUMBER"]

    rows = []
    for item in data:
        user = item.get("user") or {}
        # Extract pull number from _links or pull_request_url
        pull_number = 0
        pr_url = item.get("pull_request_url", "") or ""
        if pr_url:
            parts = pr_url.rstrip("/").split("/")
            try:
                pull_number = int(parts[-1])
            except (ValueError, IndexError):
                pass
        # Also try html_url pattern: .../pull/123#...
        if pull_number == 0:
            html_url = item.get("html_url", "") or ""
            if "/pull/" in html_url:
                try:
                    pull_number = int(html_url.split("/pull/")[1].split("#")[0].split("/")[0])
                except (ValueError, IndexError):
                    pass

        rows.append((
            item.get("id", 0),
            pull_number,
            user.get("login", "") if isinstance(user, dict) else "",
            item.get("state", ""),
            item.get("submitted_at"),
            json.dumps(item),
        ))

    total = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        total += _merge_batch(conn, table_name, columns, key_columns, rows[i:i + batch_size], variant_columns={"RAW_JSON"})

    print(f"  Loaded {total} reviews into {table_name}")
    return total
