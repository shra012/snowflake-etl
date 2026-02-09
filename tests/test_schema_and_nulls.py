from src.docs_pipeline.snowflake import get_connection
from src.docs_pipeline.config import tbl
import pytest


def test_tables_columns_and_nullability():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # SITEMAP_STAGING DOCUMENT_URL is NOT NULL
            cur.execute("SELECT COLUMN_NAME, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s", (tbl('SITEMAP_STAGING'),))
            cols = {r[0]: r[1] for r in cur.fetchall()}
            assert 'DOCUMENT_URL' in cols
            assert cols['DOCUMENT_URL'] == 'NO'

            # DOCS_MASTER has FIRST_SEEN_AT and LAST_SEEN_AT not null
            cur.execute("SELECT COLUMN_NAME, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s", (tbl('DOCS_MASTER'),))
            cols2 = {r[0]: r[1] for r in cur.fetchall()}
            assert 'FIRST_SEEN_AT' in cols2
            assert 'LAST_SEEN_AT' in cols2

            # DOCUMENT_CONTENT DOCUMENT_URL NOT NULL
            cur.execute("SELECT COLUMN_NAME, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s", (tbl('DOCUMENT_CONTENT'),))
            cols3 = {r[0]: r[1] for r in cur.fetchall()}
            assert 'DOCUMENT_URL' in cols3
            assert cols3['DOCUMENT_URL'] == 'NO'
    finally:
        conn.close()


def test_insert_null_document_url_fails():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            with pytest.raises(Exception):
                cur.execute(f"INSERT INTO {tbl('SITEMAP_STAGING')} (RUN_ID, SOURCE_IDENTIFIER, SITEMAP_URL, DOCUMENT_URL) VALUES (%s,%s,%s,%s)", ('r1','s','su', None))
    finally:
        conn.close()
