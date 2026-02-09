"""Tests for src.github_pipeline.config."""
import os
from unittest.mock import patch

import pytest

from src.github_pipeline.config import (
    get_github_token,
    get_headers,
    get_sheets_spreadsheet_id,
    get_google_credentials_path,
)


# ── get_github_token ────────────────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
def test_get_github_token_returns_token():
    assert get_github_token() == "ghp_test123"


@patch.dict(os.environ, {}, clear=True)
def test_get_github_token_raises_when_missing():
    # Remove GITHUB_TOKEN if set by dotenv
    os.environ.pop("GITHUB_TOKEN", None)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        get_github_token()


# ── get_headers ─────────────────────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_abc"})
def test_get_headers_includes_auth():
    headers = get_headers()
    assert headers == {"Authorization": "token ghp_abc"}


# ── get_sheets_spreadsheet_id ───────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_SHEETS_SPREADSHEET_ID": "sheet123"})
def test_get_sheets_spreadsheet_id_returns_id():
    assert get_sheets_spreadsheet_id() == "sheet123"


@patch.dict(os.environ, {}, clear=True)
def test_get_sheets_spreadsheet_id_raises_when_missing():
    os.environ.pop("GITHUB_SHEETS_SPREADSHEET_ID", None)
    with pytest.raises(RuntimeError, match="GITHUB_SHEETS_SPREADSHEET_ID"):
        get_sheets_spreadsheet_id()


# ── get_google_credentials_path ─────────────────────────────────────────────

@patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds.json"})
def test_get_google_credentials_path_returns_path():
    assert get_google_credentials_path() == "/path/to/creds.json"


@patch.dict(os.environ, {}, clear=True)
def test_get_google_credentials_path_raises_when_missing():
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    with pytest.raises(RuntimeError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        get_google_credentials_path()
