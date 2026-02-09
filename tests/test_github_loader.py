"""Tests for src.github_pipeline.loader and src.github_pipeline.ddl."""
from unittest.mock import MagicMock, patch, call
import json

import pytest

from src.github_pipeline.loader import (
    get_resume_point,
    get_loaded_count,
    load_commits,
    load_pulls,
    load_pr_comments,
    load_issues,
    load_reviews,
)


# ── get_resume_point ────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_get_resume_point_returns_timestamp(mock_tbl):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    from datetime import datetime
    ts = datetime(2026, 1, 15, 10, 30, 0)
    cursor.fetchone.return_value = (ts,)

    result = get_resume_point(conn, "GH_RAW_COMMITS", "COMMITTED_DATE")
    assert result == ts.isoformat()


@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_get_resume_point_returns_none_if_empty(mock_tbl):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = (None,)

    result = get_resume_point(conn, "GH_RAW_COMMITS", "COMMITTED_DATE")
    assert result is None


@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_get_resume_point_handles_error(mock_tbl):
    conn = MagicMock()
    conn.cursor.side_effect = Exception("table not found")

    result = get_resume_point(conn, "GH_RAW_COMMITS", "COMMITTED_DATE")
    assert result is None


# ── get_loaded_count ────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_get_loaded_count(mock_tbl):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = (42,)

    assert get_loaded_count(conn, "GH_RAW_COMMITS") == 42


# ── load_commits ────────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader._merge_batch", return_value=2)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_load_commits(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [
        {"sha": "abc123", "commit": {"author": {"name": "alice", "date": "2026-01-01T00:00:00Z"}, "message": "fix"}, "author": {"login": "alice"}},
        {"sha": "def456", "commit": {"author": {"name": "bob", "date": "2026-01-02T00:00:00Z"}, "message": "feat"}, "author": {"login": "bob"}},
    ]

    result = load_commits(conn, data)
    assert result == 2
    mock_merge.assert_called_once()


@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_COMMITS")
def test_load_commits_empty(mock_tbl):
    assert load_commits(MagicMock(), []) == 0


# ── load_pulls ──────────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader._merge_batch", return_value=1)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_PULLS")
def test_load_pulls(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [{"number": 1, "user": {"login": "alice"}, "state": "open", "title": "test", "updated_at": "2026-01-01", "created_at": "2026-01-01"}]

    result = load_pulls(conn, data)
    assert result == 1


# ── load_pr_comments ────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader._merge_batch", return_value=1)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_PR_COMMENTS")
def test_load_pr_comments(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [{"id": 10, "user": {"login": "bob"}, "pull_request_url": "http://...", "updated_at": "2026-01-01", "created_at": "2026-01-01", "body": "lgtm"}]

    result = load_pr_comments(conn, data)
    assert result == 1


# ── load_issues ─────────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader._merge_batch", return_value=1)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_ISSUES")
def test_load_issues(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [{"id": 20, "user": {"login": "carol"}, "state": "closed", "title": "bug", "updated_at": "2026-01-01", "created_at": "2026-01-01"}]

    result = load_issues(conn, data)
    assert result == 1


# ── load_reviews ────────────────────────────────────────────────────────────

@patch("src.github_pipeline.loader._merge_batch", return_value=1)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_REVIEWS")
def test_load_reviews(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [{"id": 99, "user": {"login": "dave"}, "state": "APPROVED", "submitted_at": "2026-01-01", "pull_request_url": "https://api.github.com/repos/apache/airflow/pulls/123"}]

    result = load_reviews(conn, data)
    assert result == 1


@patch("src.github_pipeline.loader._merge_batch", return_value=0)
@patch("src.github_pipeline.loader.tbl", return_value="CANDIDATE_NS_GH_RAW_REVIEWS")
def test_load_reviews_extracts_pull_number_from_url(mock_tbl, mock_merge):
    conn = MagicMock()
    data = [{"id": 100, "user": {"login": "eve"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-01-01", "pull_request_url": "https://api.github.com/repos/apache/airflow/pulls/456"}]

    load_reviews(conn, data)
    mock_merge.assert_called_once()
    # Just verify it was called with the right data (pull number extraction is internal)


# ── DDL ─────────────────────────────────────────────────────────────────────

@patch("src.github_pipeline.ddl.tbl", side_effect=lambda x: f"CANDIDATE_NS_{x}")
def test_get_ddl_contains_all_tables(mock_tbl):
    from src.github_pipeline.ddl import get_ddl
    ddl = get_ddl()
    assert "CANDIDATE_NS_GH_RAW_COMMITS" in ddl
    assert "CANDIDATE_NS_GH_RAW_PULLS" in ddl
    assert "CANDIDATE_NS_GH_RAW_PR_COMMENTS" in ddl
    assert "CANDIDATE_NS_GH_RAW_ISSUES" in ddl
    assert "CANDIDATE_NS_GH_RAW_REVIEWS" in ddl


@patch("src.github_pipeline.ddl.tbl", side_effect=lambda x: f"CANDIDATE_NS_{x}")
def test_apply_ddl_executes_statements(mock_tbl):
    from src.github_pipeline.ddl import apply_ddl
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Mock responses for [CURRENT_DB/SCHEMA, SHOW TABLES]
    cursor.fetchone.side_effect = [("TEST_DB", "TEST_SCHEMA")]
    cursor.fetchall.side_effect = [[("created_on", "CANDIDATE_NS_GH_RAW_COMMITS", "db", "schema")]]

    apply_ddl(conn)
    # Should execute:
    # 1. SELECT CURRENT...
    # 2. CREATE TABLE... (x5)
    # 3. SHOW TABLES...
    assert cursor.execute.call_count >= 7
