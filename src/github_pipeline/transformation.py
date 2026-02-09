"""Transformation logic for GitHub Contributor Analytics.

Aggregates raw ingested data into a contributor analytics DataFrame
with scores, tiers, ranks, and percentiles.
"""
from __future__ import annotations
from typing import Any, Dict

import pandas as pd


def _extract_author_counts(df: pd.DataFrame, user_key: str = "user", login_key: str = "login") -> Dict[str, int]:
    """Extract author -> count mapping from a DataFrame with nested user dicts."""
    authors = df[user_key].apply(
        lambda x: x.get(login_key) if isinstance(x, dict) else None
    )
    return authors.value_counts().to_dict()


def _extract_commit_author_counts(commits_df: pd.DataFrame) -> Dict[str, int]:
    """Commits use a different structure: ``commit.author.name``."""
    authors = commits_df["commit"].apply(
        lambda x: x.get("author", {}).get("name") if isinstance(x, dict) else None
    )
    return authors.value_counts().to_dict()


def _determine_tier(commits: int, prs: int) -> str:
    """Determine contributor tier based on activity level."""
    activity = commits + prs
    if activity >= 20:
        return "core"
    elif activity >= 5:
        return "active"
    elif activity >= 1:
        return "contributor"
    return "observer"


def process_contributors(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build the contributor analytics DataFrame.

    Args:
        data: Dictionary from ``ingestion.run_ingestion()``, containing
              DataFrames keyed by ``commits``, ``pulls``, ``pr_comments``,
              ``reviews``.

    Returns:
        DataFrame with columns: ``author``, ``commits``, ``prs``,
        ``comments``, ``reviews``, ``score``, ``tier``, ``overall_rank``,
        ``tier_rank``, ``percentile``.
    """
    commit_counts = _extract_commit_author_counts(data["commits"])
    pr_counts = _extract_author_counts(data["pulls"])
    comment_counts = _extract_author_counts(data["pr_comments"])
    review_counts = _extract_author_counts(data["reviews"])

    # Union of all unique contributor names
    all_authors = set(
        list(commit_counts.keys())
        + list(pr_counts.keys())
        + list(comment_counts.keys())
        + list(review_counts.keys())
    )

    rows = []
    for author in all_authors:
        commits = commit_counts.get(author, 0)
        prs = pr_counts.get(author, 0)
        comments = comment_counts.get(author, 0)
        reviews = review_counts.get(author, 0)

        raw_score = (commits * 5) + (prs * 10) + (comments * 2) + (reviews * 3)
        score = min(raw_score, 100)
        tier = _determine_tier(commits, prs)

        rows.append({
            "author": author,
            "commits": commits,
            "prs": prs,
            "comments": comments,
            "reviews": reviews,
            "score": score,
            "tier": tier,
        })

    df = pd.DataFrame(rows)

    # Rankings
    df["overall_rank"] = df["score"].rank(method="min", ascending=False).astype(int)
    df["tier_rank"] = df.groupby("tier")["score"].rank(method="min", ascending=False).astype(int)
    df["percentile"] = (df["score"].rank(pct=True) * 100).round(2)

    # Sort by score descending
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    return df


def print_summary(df: pd.DataFrame) -> None:
    """Print the required output: top 10, tier distribution, summary stats."""
    print("Top 10 Contributors by Score:")
    print(df.head(10)[["author", "score", "tier"]])

    print("\nTier Distribution:")
    print(df["tier"].value_counts())

    print("\nSummary:")
    print(f"Total contributors: {len(df)}")
    print(f"Min score: {df['score'].min()}")
    print(f"Max score: {df['score'].max()}")
    print(f"Count achieving max score (100): {len(df[df['score'] == 100])}")
