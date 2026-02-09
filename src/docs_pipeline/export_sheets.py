"""Export Task 4 analytics results to Google Sheets."""
from __future__ import annotations
from typing import Dict, Any, List
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


from .analytics import run_analytics
from .config import get_snowflake_params

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _values_from_data(columns: List[str], rows: List[tuple]) -> List[List[Any]]:
    if not columns and not rows:
        return []
    values = [columns]
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
    print(f"Using Google Service Account: {creds.service_account_email}")
    service = build("sheets", "v4", credentials=creds)
    return service


def _get_existing_sheet_titles(service, spreadsheet_id: str) -> set[str]:
    """Fetch existing sheet titles to avoid duplicate creation errors."""
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return {s['properties']['title'] for s in spreadsheet.get('sheets', [])}
    except HttpError as e:
        if e.resp.status == 404:
            raise RuntimeError(f"Spreadsheet '{spreadsheet_id}' not found. Please ensure the SERVICE ACCOUNT EMAIL has 'Editor' access to this sheet.") from e
        print(f"Warning: Could not fetch spreadsheet metadata: {e}")
        return set()
    except Exception as e:
        print(f"Warning: Could not fetch spreadsheet metadata: {e}")
        return set()


def export_to_sheets(conn, spreadsheet_id: str, credentials_path: str | None = None):
    results = run_analytics(conn)
    service = _get_sheets_service(credentials_path)
    sheet_service = service.spreadsheets()

    # Get existing sheets to decide whether to create or just update
    existing_titles = _get_existing_sheet_titles(service, spreadsheet_id)
    print(f"Found existing sheets: {sorted(list(existing_titles))}")

    # For each query id, write to a sheet named with the query id
    for qid, rows in results.items():
        sheet_title = qid
        print(f"Processing query '{qid}' -> Sheet '{sheet_title}'")

        if sheet_title not in existing_titles:
            # Create the sheet
            print(f"Attempting to create sheet '{sheet_title}'...")
            try:
                body = {"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]}
                sheet_service.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
                existing_titles.add(sheet_title) # Track it as created
            except HttpError as err:
                # Fallback: if it failed but claims existence, proceed
                if err.resp.status == 400 and "already exists" in str(err):
                    pass
                else:
                    print(f"Error creating sheet '{sheet_title}': {err}")
                    # Try to proceed anyway, maybe it exists but we missed it?
                    pass



        if isinstance(rows, dict) and "rows" in rows:
            # New format with columns
            data = rows
            values = _values_from_data(data.get("columns", []), data.get("rows", []))
        else:
            # Fallback for old format (list of tuples) if ever needed
            values = _values_from_data([f"col{i+1}" for i in range(len(rows[0]))] if rows else [], rows)

        if not values:
            # write an empty marker
            values = [["no results"]]
        body = {"values": values}
        # Use quoted sheet name for safety
        range_name = f"'{sheet_title}'!A1"
        try:
            print(f"Writing {len(values)} rows to {range_name}...")
            sheet_service.values().update(spreadsheetId=spreadsheet_id, range=range_name, valueInputOption='RAW', body=body).execute()
        except Exception as e:
            print(f"Error writing to {range_name}: {e}")
            raise

    return {"spreadsheet_id": spreadsheet_id, "sheets_written": list(results.keys())}
