"""Analytics runner for Task 4 queries."""
from __future__ import annotations
from typing import Dict, Any

from .config import tbl


def _load_queries(path: str) -> Dict[str, str]:
    with open(path, 'r') as f:
        sql = f.read()
    # Split into sections using the '-- 4x' markers
    queries: Dict[str, str] = {}
    parts = sql.split('-- ')
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p.startswith('4'):
            header, *rest = p.split('\n', 1)
            body = rest[0] if rest else ''
            qid = header.split(':')[0].strip()
            # restore leading comment markers removed by split
            queries[qid] = body.strip()
    return queries


def _format_query(q: str) -> str:
    # Replace placeholder identifiers with actual table names
    q = q.replace("{DOCS_MASTER}", tbl('DOCS_MASTER'))
    q = q.replace("{DOCUMENT_CONTENT}", tbl('DOCUMENT_CONTENT'))
    q = q.replace("{SITEMAP_STAGING}", tbl('SITEMAP_STAGING'))
    return q


def run_analytics(conn) -> Dict[str, Any]:
    queries = _load_queries('sql/task4_analytics.sql')
    results: Dict[str, Any] = {}
    with conn.cursor() as cur:
        for qid, q in sorted(queries.items()):
            sql = _format_query(q)
            cur.execute(sql)
            results[qid] = cur.fetchall()
    return results


if __name__ == '__main__':
    print('Use run_analytics(conn) from your environment to execute the queries.')
