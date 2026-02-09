"""Tests for src.github_pipeline.export_sheets."""
import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.github_pipeline.export_sheets import (
    _df_to_values,
    _get_existing_sheet_titles,
    export_to_sheets,
)


# ── _df_to_values ───────────────────────────────────────────────────────────

def test_df_to_values_includes_headers_and_rows():
    df = pd.DataFrame({"name": ["alice", "bob"], "score": [10, 20]})
    values = _df_to_values(df)
    assert values[0] == ["name", "score"]
    assert values[1] == ["alice", "10"]
    assert values[2] == ["bob", "20"]


def test_df_to_values_handles_nan():
    df = pd.DataFrame({"a": [1, None]})
    values = _df_to_values(df)
    assert values[2] == [""]  # NaN -> empty string


def test_df_to_values_empty_df():
    df = pd.DataFrame({"a": []})
    values = _df_to_values(df)
    assert values == [["a"]]  # Just headers


# ── _get_existing_sheet_titles ──────────────────────────────────────────────

def test_get_existing_titles_returns_set():
    mock_service = MagicMock()
    mock_service.spreadsheets().get().execute.return_value = {
        "sheets": [
            {"properties": {"title": "Sheet1"}},
            {"properties": {"title": "Data"}},
        ]
    }
    titles = _get_existing_sheet_titles(mock_service, "test_id")
    assert titles == {"Sheet1", "Data"}


def test_get_existing_titles_raises_on_404():
    from googleapiclient.errors import HttpError

    mock_service = MagicMock()
    resp = MagicMock()
    resp.status = 404
    mock_service.spreadsheets().get().execute.side_effect = HttpError(
        resp, b"not found"
    )
    with pytest.raises(RuntimeError, match="not found"):
        _get_existing_sheet_titles(mock_service, "bad_id")


# ── export_to_sheets ───────────────────────────────────────────────────────

@patch("src.github_pipeline.export_sheets._get_sheets_service")
@patch("src.github_pipeline.export_sheets._get_existing_sheet_titles")
def test_export_to_sheets_creates_new_sheet(mock_titles, mock_service):
    mock_titles.return_value = set()  # no existing sheets
    mock_svc = MagicMock()
    mock_service.return_value = mock_svc

    df = pd.DataFrame({"author": ["alice"], "score": [42]})
    result = export_to_sheets(df, "spreadsheet_abc", sheet_title="TestSheet")

    # Should create the sheet
    mock_svc.spreadsheets().batchUpdate.assert_called_once()
    # Should write data
    mock_svc.spreadsheets().values().update.assert_called_once()
    assert result["spreadsheet_id"] == "spreadsheet_abc"
    assert result["sheet_title"] == "TestSheet"


@patch("src.github_pipeline.export_sheets._get_sheets_service")
@patch("src.github_pipeline.export_sheets._get_existing_sheet_titles")
def test_export_to_sheets_clears_existing_sheet(mock_titles, mock_service):
    mock_titles.return_value = {"TestSheet"}  # sheet exists
    mock_svc = MagicMock()
    mock_service.return_value = mock_svc

    df = pd.DataFrame({"author": ["alice"], "score": [42]})
    result = export_to_sheets(df, "spreadsheet_abc", sheet_title="TestSheet")

    # Should NOT create the sheet
    mock_svc.spreadsheets().batchUpdate.assert_not_called()
    # Should clear existing data
    mock_svc.spreadsheets().values().clear.assert_called_once()
    # Should write data
    mock_svc.spreadsheets().values().update.assert_called_once()


@patch("src.github_pipeline.export_sheets._get_sheets_service")
@patch("src.github_pipeline.export_sheets._get_existing_sheet_titles")
def test_export_to_sheets_data_format(mock_titles, mock_service):
    mock_titles.return_value = set()
    mock_svc = MagicMock()
    mock_service.return_value = mock_svc

    df = pd.DataFrame({"col_a": ["x"], "col_b": [99]})
    export_to_sheets(df, "sid", sheet_title="T")

    # Verify the body passed to update
    call_kwargs = mock_svc.spreadsheets().values().update.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
    assert body["values"][0] == ["col_a", "col_b"]
    assert body["values"][1] == ["x", "99"]
