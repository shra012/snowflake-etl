from datetime import datetime
from time import sleep

from src.docs_pipeline import consolidate, sitemap_extract
from src.docs_pipeline.snowflake import get_connection
from src.docs_pipeline.config import tbl


def setup_staging_for_run(conn, run_id, rows):
    # rows: list of tuples (source_identifier, sitemap_url, document_url, lastmod)
    for batch in sitemap_extract.batch_rows(rows, batch_size=100):
        sitemap_extract.insert_sitemap_staging(conn, run_id, batch)


def read_doc_master(conn, doc_url):
    with conn.cursor() as cur:
        cur.execute(f"SELECT DOCUMENT_URL, SOURCES::STRING, FIRST_SEEN_AT, LAST_SEEN_AT, LASTMOD FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL = %s", (doc_url,))
        return cur.fetchone()


def test_consolidate_idempotent():
    conn = get_connection()
    # Ensure DDL exists
    from src.docs_pipeline.ddl import docs_master_ddl
    with conn.cursor() as cur:
        cur.execute(docs_master_ddl())

    # Clean up any pre-existing test rows for a clean slate
    test_run1 = "run_consolidate_1"
    test_run2 = "run_consolidate_2"

    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {tbl('SITEMAP_STAGING')} WHERE RUN_ID IN (%s,%s)", (test_run1, test_run2))
        cur.execute(f"DELETE FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")

    # Run 1: source A has doc1 and doc2
    rows_run1 = [
        ("A", "s1", "https://example.com/doc1", None),
        ("A", "s1", "https://example.com/doc2", None),
    ]
    setup_staging_for_run(conn, test_run1, rows_run1)

    summary1 = consolidate.consolidate_run(conn, test_run1)
    assert summary1["inserted_from_staging"] == 2

    # Check docs master now has 2 rows
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")
        result = cur.fetchone()
        assert result is not None
        assert result[0] == 2

    # Keep copy of FIRST_SEEN_AT for doc1
    row1 = read_doc_master(conn, "https://example.com/doc1")
    assert row1 is not None
    first_seen = row1[2]

    # small sleep to ensure timestamps differ on update
    sleep(1)

    # Run 2: source B has doc1 and doc3
    rows_run2 = [
        ("B", "s2", "https://example.com/doc1", None),
        ("B", "s2", "https://example.com/doc3", None),
    ]
    setup_staging_for_run(conn, test_run2, rows_run2)

    summary2 = consolidate.consolidate_run(conn, test_run2)
    assert summary2["inserted_from_staging"] == 2

    # After second run: total should be 3 unique docs
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")
        result = cur.fetchone()
        assert result is not None
        assert result[0] == 3

    # doc1 should have sources A and B
    with conn.cursor() as cur:
        cur.execute(f"SELECT f.value::string AS src FROM {tbl('DOCS_MASTER')}, LATERAL FLATTEN(input => SOURCES) f WHERE DOCUMENT_URL=%s ORDER BY src", ("https://example.com/doc1",))
        sources = [r[0] for r in cur.fetchall()]
        assert "A" in sources and "B" in sources

    # FIRST_SEEN_AT for doc1 should be unchanged, LAST_SEEN_AT should be updated (later)
    row1_after = read_doc_master(conn, "https://example.com/doc1")
    assert row1_after is not None
    assert row1_after[2] == first_seen
    assert row1_after[3] >= first_seen

    # Cleanup test rows
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {tbl('SITEMAP_STAGING')} WHERE RUN_ID IN (%s,%s)", (test_run1, test_run2))
        cur.execute(f"DELETE FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")
    conn.close()
