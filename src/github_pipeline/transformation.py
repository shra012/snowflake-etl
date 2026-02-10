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
            "raw_score": raw_score,
            "score": score,
            "tier": tier,
        })

    df = pd.DataFrame(rows)

    # Rankings
    # Rank by raw_score for better differentiation among top contributors
    df["overall_rank"] = df["raw_score"].rank(method="min", ascending=False).astype(int)
    df["tier_rank"] = df.groupby("tier")["raw_score"].rank(method="min", ascending=False).astype(int)
    df["percentile"] = (df["raw_score"].rank(pct=True) * 100).round(2)

    # Sort by score descending
    df = df.sort_values("raw_score", ascending=False).reset_index(drop=True)

    return df


def process_contributors_from_snowflake(conn) -> pd.DataFrame:
    """Build the contributor analytics DataFrame directly from Snowflake.

    Instead of parsing RAW_JSON in Python, this aggregates the structured
    ``AUTHOR_LOGIN`` columns using SQL, then applies scoring and ranking
    in Pandas.  Much faster than pulling full JSON blobs.

    Args:
        conn: Active Snowflake connection.

    Returns:
        Same schema as ``process_contributors``: ``author``, ``commits``,
        ``prs``, ``comments``, ``reviews``, ``raw_score``, ``score``,
        ``tier``, ``overall_rank``, ``tier_rank``, ``percentile``.
    """
    from src.docs_pipeline.config import tbl

    sql = f"""
    WITH commit_counts AS (
        SELECT AUTHOR_LOGIN AS author, COUNT(*) AS commits
        FROM {tbl('GH_RAW_COMMITS')}
        WHERE AUTHOR_LOGIN IS NOT NULL AND AUTHOR_LOGIN != ''
        GROUP BY AUTHOR_LOGIN
    ),
    pr_counts AS (
        SELECT AUTHOR_LOGIN AS author, COUNT(*) AS prs
        FROM {tbl('GH_RAW_PULLS')}
        WHERE AUTHOR_LOGIN IS NOT NULL AND AUTHOR_LOGIN != ''
        GROUP BY AUTHOR_LOGIN
    ),
    comment_counts AS (
        SELECT AUTHOR_LOGIN AS author, COUNT(*) AS comments
        FROM {tbl('GH_RAW_PR_COMMENTS')}
        WHERE AUTHOR_LOGIN IS NOT NULL AND AUTHOR_LOGIN != ''
        GROUP BY AUTHOR_LOGIN
    ),
    review_counts AS (
        SELECT AUTHOR_LOGIN AS author, COUNT(*) AS reviews
        FROM {tbl('GH_RAW_REVIEWS')}
        WHERE AUTHOR_LOGIN IS NOT NULL AND AUTHOR_LOGIN != ''
        GROUP BY AUTHOR_LOGIN
    ),
    all_authors AS (
        SELECT author FROM commit_counts
        UNION
        SELECT author FROM pr_counts
        UNION
        SELECT author FROM comment_counts
        UNION
        SELECT author FROM review_counts
    )
    SELECT
        a.author,
        COALESCE(c.commits, 0)  AS commits,
        COALESCE(p.prs, 0)      AS prs,
        COALESCE(cm.comments, 0) AS comments,
        COALESCE(r.reviews, 0)  AS reviews
    FROM all_authors a
    LEFT JOIN commit_counts  c  ON c.author  = a.author
    LEFT JOIN pr_counts      p  ON p.author  = a.author
    LEFT JOIN comment_counts cm ON cm.author = a.author
    LEFT JOIN review_counts  r  ON r.author  = a.author
    ORDER BY a.author
    """

    print("Querying contributor counts from Snowflake...")
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [desc[0].lower() for desc in cur.description]
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=cols)
    print(f"  Found {len(df)} unique contributors")

    # Scoring: raw_score is uncapped, score is capped at 100 per spec
    df["raw_score"] = (
        df["commits"] * 5 + df["prs"] * 10 + df["comments"] * 2 + df["reviews"] * 3
    )
    df["score"] = df["raw_score"].clip(upper=100)

    # Tier assignment
    df["tier"] = df.apply(lambda r: _determine_tier(r["commits"], r["prs"]), axis=1)

    # Rank by raw_score for better differentiation among top contributors
    df["overall_rank"] = df["raw_score"].rank(method="min", ascending=False).astype(int)
    df["tier_rank"] = df.groupby("tier")["raw_score"].rank(method="min", ascending=False).astype(int)
    df["percentile"] = (df["raw_score"].rank(pct=True) * 100).round(2)

    # Sort by raw_score descending
    df = df.sort_values("raw_score", ascending=False).reset_index(drop=True)

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
