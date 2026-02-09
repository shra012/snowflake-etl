from src.docs_pipeline.analytics import _load_queries, _format_query
from src.docs_pipeline.config import tbl


def test_sql_file_contains_all_sections():
    queries = _load_queries('sql/task4_analytics.sql')
    assert '4a' in queries
    assert '4b' in queries
    assert '4c' in queries
    assert '4d' in queries
    assert '4e' in queries


def test_format_query_replaces_placeholders():
    queries = _load_queries('sql/task4_analytics.sql')
    q = queries['4a']
    formatted = _format_query(q)
    # after formatting, should contain the actual table name
    assert tbl('DOCS_MASTER') in formatted
