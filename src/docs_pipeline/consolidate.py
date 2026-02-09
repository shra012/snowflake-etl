"""Consolidation logic (Task 2).

Provides set-based MERGE from SITEMAP_STAGING (for a given run_id) into DOCS_MASTER.
Ensures idempotency and updates FIRST_SEEN_AT/LAST_SEEN_AT and SOURCES union.
"""
from __future__ import annotations
from typing import Dict, Any

from .config import tbl


def _merge_sql() -> str:
    return f"""
MERGE INTO {tbl('DOCS_MASTER')} AS t
USING (
  SELECT
    DOCUMENT_URL,
    ARRAY_AGG(DISTINCT SOURCE_IDENTIFIER) AS SOURCES,
    MAX(LASTMOD) AS LASTMOD
  FROM {tbl('SITEMAP_STAGING')}
  WHERE RUN_ID = %(run_id)s
  GROUP BY DOCUMENT_URL
) AS s
ON t.DOCUMENT_URL = s.DOCUMENT_URL
WHEN MATCHED THEN UPDATE SET
  t.SOURCES = ARRAY_DISTINCT(ARRAY_CAT(t.SOURCES, s.SOURCES)),
  t.LAST_SEEN_AT = CURRENT_TIMESTAMP(),
  t.LASTMOD = COALESCE(GREATEST(t.LASTMOD, s.LASTMOD), t.LASTMOD, s.LASTMOD),
  t.UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (DOCUMENT_URL, SOURCES, FIRST_SEEN_AT, LAST_SEEN_AT, LASTMOD)
VALUES (s.DOCUMENT_URL, s.SOURCES, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), s.LASTMOD);
"""


def consolidate_run(conn, run_id: str) -> Dict[str, Any]:
    """Run a consolidation MERGE for the given run_id.

    Returns a dict with summary info. The Snowflake connector's cursor does not
    reliably report number of affected rows after MERGE, so the summary includes
    counts observed before and after to show changes.
    Also records pipeline metrics and raises alerts when thresholds exceeded.
    """
    from datetime import datetime
    from .observability import record_pipeline_metrics, raise_alert

    started = datetime.utcnow()
    summary = {"run_id": run_id, "inserted_from_staging": 0, "docs_master_count_before": None, "docs_master_count_after": None}

    with conn.cursor() as cur:
        # count master before
        cur.execute(f"SELECT COUNT(*) FROM {tbl('DOCS_MASTER')}")
        summary["docs_master_count_before"] = cur.fetchone()[0]

        # count staging rows for this run
        cur.execute(f"SELECT COUNT(DISTINCT DOCUMENT_URL) FROM {tbl('SITEMAP_STAGING')} WHERE RUN_ID = %s", (run_id,))
        staged = cur.fetchone()[0]
        summary["inserted_from_staging"] = staged

        # perform the merge
        cur.execute(_merge_sql(), {"run_id": run_id})

        # count master after
        cur.execute(f"SELECT COUNT(*) FROM {tbl('DOCS_MASTER')}")
        summary["docs_master_count_after"] = cur.fetchone()[0]

    ended = datetime.utcnow()
    try:
        record_pipeline_metrics(conn, run_id, 'consolidate', 'merge', started, ended, rows_input=staged, rows_output=summary["docs_master_count_after"], success_count=1, failure_count=0)
    except Exception:
        pass

    # example alert: warn if no rows were consolidated
    if summary["inserted_from_staging"] == 0:
        try:
            raise_alert(conn, f"NO_ROWS_{run_id}", run_id, 'no_rows', 'WARN', 'No rows were consolidated for run', metric_name='inserted_from_staging', metric_value=0, threshold=1)
        except Exception:
            pass

    return summary