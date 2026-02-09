"""Configuration for the GitHub Contributor Analytics Pipeline.

Loads environment variables (optionally from a .env file) and provides
helpers for GitHub API access and Google Sheets export.
"""
from __future__ import annotations
import os

# Load .env automatically if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── GitHub API ──────────────────────────────────────────────────────────────

BASE_URL = "https://api.github.com"
REPO = "apache/airflow"


def get_github_token() -> str:
    """Return the GitHub personal access token from the environment."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable must be set. "
            "Add it to your .env file."
        )
    return token


def get_headers() -> dict:
    """Return default headers for GitHub API requests."""
    return {"Authorization": f"token {get_github_token()}"}


# ── Google Sheets ───────────────────────────────────────────────────────────

def get_sheets_spreadsheet_id() -> str:
    """Return the target Google Sheets spreadsheet ID."""
    sid = os.environ.get("GITHUB_SHEETS_SPREADSHEET_ID", "")
    if not sid:
        raise RuntimeError(
            "GITHUB_SHEETS_SPREADSHEET_ID environment variable must be set."
        )
    return sid


def get_google_credentials_path() -> str:
    """Return the path to the Google service account JSON file."""
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not path:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS environment variable must be set."
        )
    return path
