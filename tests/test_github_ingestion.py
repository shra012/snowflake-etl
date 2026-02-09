"""Tests for src.github_pipeline.ingestion."""
import os
from unittest.mock import patch, MagicMock, call

import pytest
import requests


# ── _fetch_paginated ────────────────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")  # skip real sleeps
def test_fetch_paginated_single_page(mock_sleep, mock_get):
    """Single page with no pagination link returns that page's data."""
    from src.github_pipeline.ingestion import _fetch_paginated

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [{"id": 1}, {"id": 2}]
    resp.links = {}  # no next page
    mock_get.return_value = resp

    result = _fetch_paginated("/repos/test/commits", max_pages=3)
    assert result == [{"id": 1}, {"id": 2}]
    mock_get.assert_called_once()


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_multiple_pages(mock_sleep, mock_get):
    """Follows pagination links until max_pages is reached."""
    from src.github_pipeline.ingestion import _fetch_paginated

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = [{"id": 1}]
    page1.links = {"next": {"url": "https://api.github.com/page2"}}

    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = [{"id": 2}]
    page2.links = {}

    mock_get.side_effect = [page1, page2]

    result = _fetch_paginated("/repos/test/commits", max_pages=5)
    assert result == [{"id": 1}, {"id": 2}]
    assert mock_get.call_count == 2


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_respects_max_pages(mock_sleep, mock_get):
    """Stops after max_pages even if more pages available."""
    from src.github_pipeline.ingestion import _fetch_paginated

    page = MagicMock()
    page.status_code = 200
    page.json.return_value = [{"id": 1}]
    page.links = {"next": {"url": "https://api.github.com/nextpage"}}
    mock_get.return_value = page

    result = _fetch_paginated("/repos/test/commits", max_pages=2)
    assert len(result) == 2  # 1 item per page, 2 pages
    assert mock_get.call_count == 2


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_handles_error_status(mock_sleep, mock_get):
    """Stops on non-200, non-403 status codes."""
    from src.github_pipeline.ingestion import _fetch_paginated

    resp = MagicMock()
    resp.status_code = 500
    mock_get.return_value = resp

    result = _fetch_paginated("/repos/test/commits", max_pages=3)
    assert result == []


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_retries_on_network_error(mock_sleep, mock_get):
    """Retries on ChunkedEncodingError then succeeds."""
    from src.github_pipeline.ingestion import _fetch_paginated

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [{"id": 1}]
    resp.links = {}

    # First call raises, second succeeds
    mock_get.side_effect = [
        requests.exceptions.ChunkedEncodingError("premature end"),
        resp,
    ]

    result = _fetch_paginated("/repos/test/commits", max_pages=1)
    assert result == [{"id": 1}]
    assert mock_get.call_count == 2


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_gives_up_after_max_retries(mock_sleep, mock_get):
    """Returns empty list if all retries fail."""
    from src.github_pipeline.ingestion import _fetch_paginated

    mock_get.side_effect = requests.exceptions.ConnectionError("refused")

    result = _fetch_paginated("/repos/test/commits", max_pages=1)
    assert result == []
    assert mock_get.call_count == 3  # max_retries = 3


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.requests.get")
@patch("src.github_pipeline.ingestion.time.sleep")
def test_fetch_paginated_page_callback_called_per_page(mock_sleep, mock_get):
    """page_callback is invoked once per page with that page's data."""
    from src.github_pipeline.ingestion import _fetch_paginated

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = [{"id": 1}]
    page1.links = {"next": {"url": "https://api.github.com/page2"}}

    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = [{"id": 2}, {"id": 3}]
    page2.links = {}

    mock_get.side_effect = [page1, page2]
    cb = MagicMock()

    result = _fetch_paginated("/repos/test/commits", max_pages=5, page_callback=cb)
    assert len(result) == 3
    assert cb.call_count == 2
    cb.assert_any_call([{"id": 1}])
    cb.assert_any_call([{"id": 2}, {"id": 3}])


# ── Endpoint helpers ────────────────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_commits_calls_paginated(mock_fp):
    from src.github_pipeline.ingestion import fetch_commits
    mock_fp.return_value = [{"sha": "abc"}]

    result = fetch_commits(max_pages=1)
    assert result == [{"sha": "abc"}]
    mock_fp.assert_called_once()
    args, kwargs = mock_fp.call_args
    assert "/commits" in args[0]


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_pulls_calls_paginated(mock_fp):
    from src.github_pipeline.ingestion import fetch_pulls
    mock_fp.return_value = [{"number": 1}]

    result = fetch_pulls(max_pages=1)
    assert result == [{"number": 1}]
    args, kwargs = mock_fp.call_args
    assert "/pulls" in args[0]
    assert kwargs["params"]["state"] == "all"


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_pr_comments_calls_paginated(mock_fp):
    from src.github_pipeline.ingestion import fetch_pr_comments
    mock_fp.return_value = [{"id": 10}]

    result = fetch_pr_comments(max_pages=1)
    assert result == [{"id": 10}]
    args, _ = mock_fp.call_args
    assert "/pulls/comments" in args[0]


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_issues_calls_paginated(mock_fp):
    from src.github_pipeline.ingestion import fetch_issues
    mock_fp.return_value = [{"id": 20}]

    result = fetch_issues(max_pages=1)
    assert result == [{"id": 20}]
    args, kwargs = mock_fp.call_args
    assert "/issues" in args[0]


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_reviews_iterates_prs(mock_fp):
    from src.github_pipeline.ingestion import fetch_reviews
    mock_fp.return_value = [{"id": 99}]

    result = fetch_reviews([101, 102], max_prs=2)
    assert len(result) == 2  # one review per PR
    assert mock_fp.call_count == 2


@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion._fetch_paginated")
def test_fetch_reviews_streams_via_callback(mock_fp):
    """Reviews page_callback is called once per PR batch."""
    from src.github_pipeline.ingestion import fetch_reviews
    mock_fp.return_value = [{"id": 99}]
    cb = MagicMock()

    fetch_reviews([101, 102], max_prs=2, page_callback=cb)
    assert cb.call_count == 2


# ── run_ingestion ───────────────────────────────────────────────────────────

@patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
@patch("src.github_pipeline.ingestion.fetch_reviews")
@patch("src.github_pipeline.ingestion.fetch_issues")
@patch("src.github_pipeline.ingestion.fetch_pr_comments")
@patch("src.github_pipeline.ingestion.fetch_pulls")
@patch("src.github_pipeline.ingestion.fetch_commits")
def test_run_ingestion_returns_all_keys(mock_commits, mock_pulls, mock_comments, mock_issues, mock_reviews):
    from src.github_pipeline.ingestion import run_ingestion

    mock_commits.return_value = [{"commit": {"author": {"name": "alice"}}}]
    mock_pulls.return_value = [{"number": 1, "user": {"login": "alice"}}]
    mock_comments.return_value = [{"user": {"login": "alice"}}]
    mock_issues.return_value = [{"user": {"login": "alice"}}]
    mock_reviews.return_value = [{"user": {"login": "alice"}}]

    result = run_ingestion()
    assert set(result.keys()) == {"commits", "pulls", "pr_comments", "issues", "reviews"}
    for key in result:
        assert len(result[key]) >= 1
