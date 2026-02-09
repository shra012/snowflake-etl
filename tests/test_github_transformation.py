"""Tests for src.github_pipeline.transformation."""
import pandas as pd
import pytest

from src.github_pipeline.transformation import (
    _extract_author_counts,
    _extract_commit_author_counts,
    _determine_tier,
    process_contributors,
    print_summary,
)


# ── _extract_author_counts ──────────────────────────────────────────────────

def test_extract_author_counts_basic():
    df = pd.DataFrame({
        "user": [
            {"login": "alice"},
            {"login": "bob"},
            {"login": "alice"},
        ]
    })
    counts = _extract_author_counts(df)
    assert counts == {"alice": 2, "bob": 1}


def test_extract_author_counts_handles_none():
    df = pd.DataFrame({"user": [None, {"login": "alice"}, "not_a_dict"]})
    counts = _extract_author_counts(df)
    assert counts == {"alice": 1}


# ── _extract_commit_author_counts ───────────────────────────────────────────

def test_extract_commit_author_counts():
    df = pd.DataFrame({
        "commit": [
            {"author": {"name": "alice"}},
            {"author": {"name": "alice"}},
            {"author": {"name": "bob"}},
        ]
    })
    counts = _extract_commit_author_counts(df)
    assert counts == {"alice": 2, "bob": 1}


def test_extract_commit_author_counts_handles_missing():
    df = pd.DataFrame({
        "commit": [
            {"author": {}},  # no name
            None,
            {"author": {"name": "carol"}},
        ]
    })
    counts = _extract_commit_author_counts(df)
    assert counts.get("carol") == 1


# ── _determine_tier ─────────────────────────────────────────────────────────

def test_tier_core():
    assert _determine_tier(10, 10) == "core"
    assert _determine_tier(20, 0) == "core"


def test_tier_active():
    assert _determine_tier(3, 2) == "active"
    assert _determine_tier(0, 5) == "active"


def test_tier_contributor():
    assert _determine_tier(1, 0) == "contributor"
    assert _determine_tier(0, 1) == "contributor"


def test_tier_observer():
    assert _determine_tier(0, 0) == "observer"


# ── process_contributors ───────────────────────────────────────────────────

def _make_test_data():
    """Build minimal test data that mirrors ingestion output."""
    return {
        "commits": pd.DataFrame({
            "commit": [
                {"author": {"name": "alice"}},
                {"author": {"name": "alice"}},
                {"author": {"name": "bob"}},
            ]
        }),
        "pulls": pd.DataFrame({
            "user": [
                {"login": "alice"},
                {"login": "alice"},
                {"login": "alice"},
                {"login": "bob"},
            ]
        }),
        "pr_comments": pd.DataFrame({
            "user": [
                {"login": "alice"},
                {"login": "carol"},
            ]
        }),
        "reviews": pd.DataFrame({
            "user": [
                {"login": "bob"},
            ]
        }),
    }


def test_process_contributors_output_columns():
    df = process_contributors(_make_test_data())
    expected_cols = {
        "author", "commits", "prs", "comments", "reviews",
        "score", "tier", "overall_rank", "tier_rank", "percentile",
    }
    assert set(df.columns) == expected_cols


def test_process_contributors_scoring():
    df = process_contributors(_make_test_data())
    alice = df[df["author"] == "alice"].iloc[0]
    # alice: 2 commits, 3 prs, 1 comment, 0 reviews
    # raw = (2*5) + (3*10) + (1*2) + (0*3) = 10 + 30 + 2 = 42
    assert alice["score"] == 42
    assert alice["tier"] == "active"  # 2+3 = 5 >= 5


def test_process_contributors_score_capped_at_100():
    data = _make_test_data()
    # Give alice 50 commits => raw = (50*5) = 250 alone
    data["commits"] = pd.DataFrame({
        "commit": [{"author": {"name": "alice"}}] * 50
    })
    df = process_contributors(data)
    alice = df[df["author"] == "alice"].iloc[0]
    assert alice["score"] == 100


def test_process_contributors_ranking():
    df = process_contributors(_make_test_data())
    # Sorted by score descending
    scores = df["score"].tolist()
    assert scores == sorted(scores, reverse=True)
    # First row has overall_rank 1
    assert df.iloc[0]["overall_rank"] == 1


def test_process_contributors_percentile_range():
    df = process_contributors(_make_test_data())
    assert df["percentile"].min() >= 0
    assert df["percentile"].max() <= 100


# ── print_summary ───────────────────────────────────────────────────────────

def test_print_summary_runs_without_error(capsys):
    df = process_contributors(_make_test_data())
    print_summary(df)
    captured = capsys.readouterr()
    assert "Top 10 Contributors" in captured.out
    assert "Tier Distribution" in captured.out
    assert "Total contributors" in captured.out
