"""Data ingestion from GitHub REST API.

Fetches commits, pull requests, PR comments, issues, and PR reviews
for the configured repository with pagination and rate-limiting.

Supports **page-by-page streaming** to Snowflake: each page of API
results is MERGEd into Snowflake immediately after fetching. If the
pipeline is interrupted mid-run, re-running it will re-fetch from
page 1, but MERGE (upsert) ensures previously loaded data is not
duplicated.  The pipeline then continues through all remaining pages.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import time

import requests

from .config import BASE_URL, REPO, get_headers


def _fetch_paginated(
    endpoint: str,
    params: Optional[dict] = None,
    max_pages: Optional[int] = None,
    page_callback: Optional[Callable[[List[dict]], None]] = None,
) -> List[dict]:
    """Fetch data from GitHub API with pagination and rate limiting.

    Args:
        endpoint: API path (e.g. ``/repos/apache/airflow/commits``).
        params: Query parameters to send with each request.
        max_pages: Maximum number of pages to retrieve. ``None`` means
                   follow pagination until all pages are fetched.
        page_callback: Optional callable invoked with each page of
                       results immediately after fetching.  Used to
                       stream data to Snowflake page-by-page.

    Returns:
        Accumulated list of JSON objects across all pages.
    """
    headers = get_headers()
    all_data: List[dict] = []
    url = f"{BASE_URL}{endpoint}"
    page_count = 0
    max_retries = 3

    while url and (max_pages is None or page_count < max_pages):
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                break  # Success, exit retry loop
            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                wait = 2 ** attempt
                if attempt < max_retries - 1:
                    print(f"  Network error (attempt {attempt + 1}/{max_retries}): {type(e).__name__}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  Failed after {max_retries} attempts: {type(e).__name__}. Skipping page.")
                    response = None

        if response is None:
            break

        if response.status_code == 200:
            data = response.json()
            page_data = data if isinstance(data, list) else [data]
            all_data.extend(page_data)
            page_count += 1

            # Stream this page to Snowflake immediately
            if page_callback and page_data:
                page_callback(page_data)

            url = response.links.get("next", {}).get("url")
            # Clear params after first request because pagination URL
            # already includes the query string.
            params = None
            time.sleep(1)  # Basic rate limiting
        elif response.status_code == 403:
            # Rate limited – wait and retry
            reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - int(time.time()), 1)
            print(f"Rate limited. Waiting {wait}s ...")
            time.sleep(wait)
        else:
            print(f"Error {response.status_code} fetching {url}")
            break

    return all_data


# ── Public endpoint-specific helpers ────────────────────────────────────────

def fetch_commits(
    max_pages: Optional[int] = None,
    page_callback: Optional[Callable] = None,
) -> List[dict]:
    """Fetch all commits. Streams each page to ``page_callback`` if provided."""
    print("Fetching commits...")
    data = _fetch_paginated(
        f"/repos/{REPO}/commits",
        params={"per_page": 100},
        max_pages=max_pages,
        page_callback=page_callback,
    )
    print(f"  Commits: {len(data)} rows")
    return data


def fetch_pulls(
    max_pages: Optional[int] = None,
    page_callback: Optional[Callable] = None,
) -> List[dict]:
    """Fetch all pull requests."""
    print("Fetching pull requests...")
    data = _fetch_paginated(
        f"/repos/{REPO}/pulls",
        params={"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"},
        max_pages=max_pages,
        page_callback=page_callback,
    )
    print(f"  Pull Requests: {len(data)} rows")
    return data


def fetch_pr_comments(
    max_pages: Optional[int] = None,
    page_callback: Optional[Callable] = None,
) -> List[dict]:
    """Fetch all PR review comments."""
    print("Fetching PR comments...")
    data = _fetch_paginated(
        f"/repos/{REPO}/pulls/comments",
        params={"per_page": 100, "sort": "updated", "direction": "desc"},
        max_pages=max_pages,
        page_callback=page_callback,
    )
    print(f"  PR Comments: {len(data)} rows")
    return data


def fetch_issues(
    max_pages: Optional[int] = None,
    page_callback: Optional[Callable] = None,
) -> List[dict]:
    """Fetch all issues."""
    print("Fetching issues...")
    data = _fetch_paginated(
        f"/repos/{REPO}/issues",
        params={"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"},
        max_pages=max_pages,
        page_callback=page_callback,
    )
    print(f"  Issues: {len(data)} rows")
    return data


def fetch_reviews(
    pull_numbers: List[int],
    max_prs: int = 500,
    page_callback: Optional[Callable] = None,
) -> List[dict]:
    """Fetch reviews for a list of pull request numbers."""
    print("Fetching reviews...")
    reviews: List[dict] = []
    for i, pr in enumerate(pull_numbers[:max_prs]):
        batch = _fetch_paginated(
            f"/repos/{REPO}/pulls/{pr}/reviews",
            max_pages=1,
        )
        reviews.extend(batch)

        # Stream each batch to Snowflake
        if page_callback and batch:
            page_callback(batch)

        if (i + 1) % 50 == 0:
            print(f"  Reviews progress: {i + 1}/{min(len(pull_numbers), max_prs)} PRs")
    print(f"  Reviews: {len(reviews)} rows")
    return reviews


# ── Orchestrator ────────────────────────────────────────────────────────────

def run_ingestion(conn=None) -> Dict[str, Any]:
    """Run the full ingestion pipeline.

    **Resume behaviour**: Every page of API results is loaded into
    Snowflake immediately via MERGE (upsert).  If the pipeline is
    interrupted, re-running it will re-fetch from page 1 while MERGE
    silently skips rows that already exist.  The pipeline then
    continues through all remaining pages.

    Args:
        conn: Optional Snowflake connection for storage and resume.

    Returns:
        Dictionary with keys ``commits``, ``pulls``, ``pr_comments``,
        ``issues``, ``reviews`` each containing a ``pandas.DataFrame``.
    """
    import pandas as pd

    # Build page-level callbacks that stream to Snowflake
    commit_cb = None
    pull_cb = None
    comment_cb = None
    issue_cb = None
    review_cb = None

    if conn:
        from .loader import (
            load_commits, load_pulls,
            load_pr_comments, load_issues, load_reviews,
        )
        from .ddl import apply_ddl
        apply_ddl(conn)

        commit_cb = lambda page: load_commits(conn, page)
        pull_cb = lambda page: load_pulls(conn, page)
        comment_cb = lambda page: load_pr_comments(conn, page)
        issue_cb = lambda page: load_issues(conn, page)
        review_cb = lambda page: load_reviews(conn, page)

    # Fetch data — each page is streamed to Snowflake immediately
    commits_data = fetch_commits(page_callback=commit_cb)
    pulls_data = fetch_pulls(page_callback=pull_cb)
    pr_comments_data = fetch_pr_comments(page_callback=comment_cb)
    issues_data = fetch_issues(page_callback=issue_cb)

    # Reviews: use pull numbers from freshly fetched pulls
    pulls_df = pd.DataFrame(pulls_data)
    pull_numbers = pulls_df["number"].tolist() if "number" in pulls_df.columns else []
    reviews_data = fetch_reviews(pull_numbers, page_callback=review_cb)

    # Print Snowflake row counts
    if conn:
        from .loader import get_loaded_count
        print("\n--- Snowflake Row Counts ---")
        for suffix in ["GH_RAW_COMMITS", "GH_RAW_PULLS", "GH_RAW_PR_COMMENTS", "GH_RAW_ISSUES", "GH_RAW_REVIEWS"]:
            print(f"  {suffix}: {get_loaded_count(conn, suffix)} rows")

    return {
        "commits": pd.DataFrame(commits_data),
        "pulls": pulls_df,
        "pr_comments": pd.DataFrame(pr_comments_data),
        "issues": pd.DataFrame(issues_data),
        "reviews": pd.DataFrame(reviews_data),
    }
