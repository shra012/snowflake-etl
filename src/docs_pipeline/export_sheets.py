"""Export Task 4 analytics results to Google Sheets."""
from __future__ import annotations
from typing import Dict, Any, List
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .analytics import run_analytics
from .config import get_snowflake_params

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _values_from_rows(rows: List[tuple]) -> List[List[Any]]:
    if not rows:
        return []
    # If rows are tuples, create header from position count
    # In practice, we expect analytics queries to provide columns; here we put raw rows with an index header
    headers = [f"col{i+1}" for i in range(len(rows[0]))]
    values = [headers]
    for r in rows:
        values.append([str(x) if x is not None else "" for x in r])
    return values


def _get_sheets_service(creds_path: str | None = None):
    # creds_path overrides GOOGLE_APPLICATION_CREDENTIALS
    if not creds_path:
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS environment variable must be set to service account JSON path or pass --sheets-credentials")
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service


def export_to_sheets(conn, spreadsheet_id: str, credentials_path: str | None = None):
    results = run_analytics(conn)
    service = _get_sheets_service(credentials_path)
    sheet_service = service.spreadsheets()

    # For each query id, write to a sheet named with the query id (create sheet if necessary)
    for qid, rows in results.items():
        sheet_title = qid
        # Try to create a sheet (ignore errors if already exists)
        try:
            body = {"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]}
            sheet_service.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        except Exception:
            # sheet likely exists
            pass

        values = _values_from_rows(rows)
        if not values:
            # write an empty marker
            values = [["no results"]]
        body = {"values": values}
        range_name = f"{sheet_title}!A1"
        sheet_service.values().update(spreadsheetId=spreadsheet_id, range=range_name, valueInputOption='RAW', body=body).execute()

    return {"spreadsheet_id": spreadsheet_id, "sheets_written": list(results.keys())}
