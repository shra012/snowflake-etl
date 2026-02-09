"""Observability helpers: record pipeline metrics and alerts in Snowflake tables."""
from __future__ import annotations
from typing import Any, Dict, Optional
from datetime import datetime

from .config import tbl


def record_pipeline_metrics(conn, run_id: str, pipeline_name: str, step_name: str, started_at: datetime, ended_at: Optional[datetime], rows_input: Optional[int] = None, rows_output: Optional[int] = None, success_count: Optional[int] = None, failure_count: Optional[int] = None, skipped_count: Optional[int] = None, notes: Optional[Dict[str, Any]] = None):
    duration = None
    if ended_at and started_at:
        duration = (ended_at - started_at).total_seconds()

    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {tbl('PIPELINE_METRICS')} (RUN_ID, PIPELINE_NAME, STEP_NAME, STARTED_AT, ENDED_AT, DURATION_SECONDS, ROWS_INPUT, ROWS_OUTPUT, SUCCESS_COUNT, FAILURE_COUNT, SKIPPED_COUNT, NOTES) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                run_id,
                pipeline_name,
                step_name,
                started_at.isoformat(),
                ended_at.isoformat() if ended_at else None,
                duration,
                rows_input,
                rows_output,
                success_count,
                failure_count,
                skipped_count,
                notes,
            ),
        )


def raise_alert(conn, alert_id: str, run_id: Optional[str], alert_type: str, severity: str, message: str, metric_name: Optional[str] = None, metric_value: Optional[float] = None, threshold: Optional[float] = None):
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {tbl('ALERTS')} (ALERT_ID, RUN_ID, ALERT_TYPE, SEVERITY, MESSAGE, METRIC_NAME, METRIC_VALUE, THRESHOLD) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (alert_id, run_id, alert_type, severity, message, metric_name, metric_value, threshold),
        )
