"""Export GitHub Contributor Analytics to Google Sheets.

Follows the same pattern as ``docs_pipeline.export_sheets`` using the
official ``google-api-python-client`` library.
"""
from __future__ import annotations
from typing import Any, List

import os
import pandas as pd

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import get_google_credentials_path

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_sheets_service(creds_path: str | None = None):
    """Build and return a Google Sheets API service."""
    if not creds_path:
        creds_path = get_google_credentials_path()
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    print(f"Using Google Service Account: {creds.service_account_email}")
    service = build("sheets", "v4", credentials=creds)
    return service


def _get_existing_sheet_titles(service, spreadsheet_id: str) -> set[str]:
    """Fetch existing sheet (tab) titles from the spreadsheet."""
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}
    except HttpError as e:
        if e.resp.status == 404:
            raise RuntimeError(
                f"Spreadsheet '{spreadsheet_id}' not found. "
                "Please ensure the SERVICE ACCOUNT EMAIL has 'Editor' access."
            ) from e
        print(f"Warning: Could not fetch spreadsheet metadata: {e}")
        return set()


def _df_to_values(df: pd.DataFrame) -> List[List[Any]]:
    """Convert a DataFrame to a list-of-lists suitable for the Sheets API."""
    headers = list(df.columns)
    rows = df.fillna("").astype(str).values.tolist()
    return [headers] + rows


def export_to_sheets(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_title: str = "Part2_Contributors",
    credentials_path: str | None = None,
) -> dict:
    """Export a DataFrame to a named sheet in an existing Google Spreadsheet.

    Args:
        df: The DataFrame to export.
        spreadsheet_id: Google Sheets spreadsheet ID.
        sheet_title: Name of the tab to create / overwrite.
        credentials_path: Optional path to service account JSON.

    Returns:
        Dict with ``spreadsheet_id`` and ``sheet_title``.
    """
    service = _get_sheets_service(credentials_path)
    sheet_service = service.spreadsheets()

    existing_titles = _get_existing_sheet_titles(service, spreadsheet_id)

    if sheet_title not in existing_titles:
        try:
            body = {"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]}
            sheet_service.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
            print(f"Created sheet '{sheet_title}'")
        except HttpError as err:
            if err.resp.status == 400 and "already exists" in str(err):
                pass
            else:
                print(f"Error creating sheet '{sheet_title}': {err}")
                raise
    else:
        # Clear existing data before writing fresh
        try:
            sheet_service.values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_title}'",
            ).execute()
        except Exception:
            pass  # If clear fails, update will still overwrite

    values = _df_to_values(df)
    range_name = f"'{sheet_title}'!A1"
    sheet_service.values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    print(f"Wrote {len(values)} rows to '{sheet_title}'")

    return {"spreadsheet_id": spreadsheet_id, "sheet_title": sheet_title}
