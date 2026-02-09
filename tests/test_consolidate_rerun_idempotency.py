from src.docs_pipeline import sitemap_extract, consolidate
from src.docs_pipeline.snowflake import get_connection
from src.docs_pipeline.config import tbl


def setup_staging_for_run(conn, run_id, rows):
    for batch in sitemap_extract.batch_rows(rows, batch_size=100):
        sitemap_extract.insert_sitemap_staging(conn, run_id, batch)


def test_consolidate_rerun_is_idempotent():
    conn = get_connection()
    try:
        test_run = 'run_rerun_test'
        # cleanup
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {tbl('SITEMAP_STAGING')} WHERE RUN_ID = %s", (test_run,))
            cur.execute(f"DELETE FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")

        rows = [
            ('A','s','https://example.com/d1', None),
            ('B','s','https://example.com/d2', None),
        ]
        setup_staging_for_run(conn, test_run, rows)

        s1 = consolidate.consolidate_run(conn, test_run)
        s2 = consolidate.consolidate_run(conn, test_run)  # run again

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")
            cnt = cur.fetchone()[0]
            assert cnt == 2
    finally:
        # cleanup
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {tbl('SITEMAP_STAGING')} WHERE RUN_ID = %s", (test_run,))
            cur.execute(f"DELETE FROM {tbl('DOCS_MASTER')} WHERE DOCUMENT_URL LIKE 'https://example.com/%'")
        conn.close()
