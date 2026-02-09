"""Minimal CLI entrypoint for the pipeline."""
import argparse
import os
import textwrap
from os import environ

from .ddl import (
    sitemap_staging_ddl,
    docs_master_ddl,
    document_content_ddl,
    pipeline_metrics_ddl,
    alerts_ddl,
)
from .snowflake import test_connection, get_connection_optional, get_connection, execute
from .sitemap_extract import run_sitemap_extract
from .consolidate import consolidate_run
from .content_fetch import run_content_fetch
from .utils import parse_key_value_list, require_connection_or_exit
from .config import get_initials, initials_is_valid


def create_tables():
    print("DDL statements (execute these against Snowflake):\n")
    for ddl in [
        sitemap_staging_ddl(),
        docs_master_ddl(),
        document_content_ddl(),
        pipeline_metrics_ddl(),
        alerts_ddl(),
    ]:
        print(textwrap.indent(ddl.strip(), "  "))
        print("\n---\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("docs-pipeline")
    parser.add_argument("--create-tables", action="store_true", help="Print DDL for tables")
    parser.add_argument("--apply-tables", action="store_true", help="Execute DDL against Snowflake (requires --yes)")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive actions (use with --apply-tables)")
    parser.add_argument("--test-connection", action="store_true", help="Run a quick Snowflake connection test and report diagnostics")
    parser.add_argument("--run-sitemap-extract", action="store_true", help="Run sitemap extraction and insert into SITEMAP_STAGING")
    parser.add_argument("--run-consolidate", action="store_true", help="Run consolidation MERGE for a run into DOCS_MASTER")
    parser.add_argument("--run-content-fetch", action="store_true", help="Fetch document contents and update DOCUMENT_CONTENT")
    parser.add_argument("--run-analytics", action="store_true", help="Run Task 4 analytics queries and print results")
    parser.add_argument("--export-sheets", action="store_true", help="Run analytics and export results to Google Sheets")
    parser.add_argument("--sheets-spreadsheet-id", type=str, help="Google Sheets spreadsheet id to export to", default=None)
    parser.add_argument("--sheets-credentials", type=str, help="Path to Google service account JSON credentials file (optional, defaults to GOOGLE_APPLICATION_CREDENTIALS)", default=None)
    parser.add_argument("--run-id", type=str, help="Run ID to attach to SITEMAP_STAGING rows or consolidation runs")
    parser.add_argument("--sitemap-sources", type=str, help="Semicolon-separated KEY=URL list of sitemap sources", default=None)
    parser.add_argument("--batch-size", type=int, help="Batch size for staging inserts", default=500)
    parser.add_argument("--max-urls", type=int, help="Limit number of sitemap document URLs to extract (smoke run)", default=None)
    parser.add_argument("--content-batch-size", type=int, help="Batch size for content fetch driver", default=100)
    parser.add_argument("--max-docs", type=int, help="Limit number of documents to fetch (smoke run)", default=None)
    parser.add_argument("--run-all", action="store_true", help="Run the full pipeline: extract -> consolidate -> fetch -> analytics -> export")
    args = parser.parse_args()

    if args.create_tables:
        create_tables()
    elif args.test_connection:
        res = test_connection()
        if res.get("ok"):
            print("Snowflake connection: OK")
            print("Version:", res.get("details", {}).get("version"))
            print("pandas available:", res.get("details", {}).get("pandas_available"))
            print("pyarrow available:", res.get("details", {}).get("pyarrow_available"))
        else:
            print("Snowflake connection: FAILED")
            print("Error:", res.get("error"))
            if res.get("traceback"):
                print("--- traceback ---")
                print(res.get("traceback"))
    elif args.apply_tables:
        if not args.yes:
            print("Refusing to apply DDL without explicit confirmation. Use --apply-tables --yes to execute the DDL.")
            raise SystemExit(2)
        # Run a quick connection test first
        res = test_connection()
        if not res.get("ok"):
            print("Cannot apply DDL because connection test failed:", res.get("error"))
            if res.get("traceback"):
                print(res.get("traceback"))
            raise SystemExit(1)
            # Execute each DDL statement
        try:
            conn = get_connection()
        except Exception as exc:
            print("Failed to create Snowflake connection:", exc)
            raise SystemExit(1)

        ddls = [
            sitemap_staging_ddl(),
            docs_master_ddl(),
            document_content_ddl(),
            pipeline_metrics_ddl(),
            alerts_ddl(),
        ]
        success = True
        for i, ddl in enumerate(ddls, 1):
            try:
                print(f"Applying DDL block {i}/{len(ddls)}...")
                execute(conn, ddl)
                print("  -> OK")
            except Exception as exc:
                success = False
                print(f"  -> FAILED: {exc}")
        conn.close()
        if not success:
            raise SystemExit(1)
    else:
        if args.run_sitemap_extract:
            # validate initials
            initials = get_initials()
            if not initials_is_valid(initials):
                print(f"INVALID INITIALS '{initials}'. Please set INITIALS env var to your initials (e.g., 'NS'). Aborting.")
                raise SystemExit(2)

            run_id = args.run_id or environ.get("SITEMAP_RUN_ID", "run_local")
            sources_env = args.sitemap_sources or environ.get("SITEMAP_SOURCES", "docs=https://docs.snowflake.com/en/sitemap.xml")
            sources = parse_key_value_list(sources_env)

            conn = get_connection_optional()
            total = run_sitemap_extract(run_id, sources, conn=conn, batch_size=args.batch_size, max_urls=args.max_urls)
            print(f"Inserted {total} sitemap rows into {run_id}")
            if conn:
                conn.close()
        elif args.run_consolidate:
            # validate initials
            initials = get_initials()
            if not initials_is_valid(initials):
                print(f"INVALID INITIALS '{initials}'. Please set INITIALS env var to your initials (e.g., 'NS'). Aborting.")
                raise SystemExit(2)

            run_id = args.run_id
            if not run_id:
                print("--run-consolidate requires --run-id")
                raise SystemExit(2)
            conn = require_connection_or_exit()
            try:
                summary = consolidate_run(conn, run_id)
                print("Consolidation summary:", summary)
            finally:
                conn.close()
        elif args.run_content_fetch:
            initials = get_initials()
            if not initials_is_valid(initials):
                print(f"INVALID INITIALS '{initials}'. Please set INITIALS env var to your initials (e.g., 'NS'). Aborting.")
                raise SystemExit(2)
            conn = require_connection_or_exit()
            try:
                settings = {}
                if args.max_docs is not None:
                    settings['max_docs'] = args.max_docs
                summary = run_content_fetch(conn, batch_size=args.content_batch_size, settings=settings)
                print('Content fetch summary:', summary)
            finally:
                conn.close()
        elif args.run_analytics:
            conn = require_connection_or_exit()
            try:
                from .analytics import run_analytics
                results = run_analytics(conn)
                for qid, rows in sorted(results.items()):
                    print(f"--- {qid} ---")
                    for r in rows:
                        print(r)
            finally:
                conn.close()
        elif args.export_sheets:
            # spreadsheets export
            conn = require_connection_or_exit()
            try:
                from .export_sheets import export_to_sheets
                sid = args.sheets_spreadsheet_id or os.environ.get('GOOGLE_SHEETS_SPREADSHEET_ID')
                if not sid:
                    print('No spreadsheet id provided via --sheets-spreadsheet-id or GOOGLE_SHEETS_SPREADSHEET_ID')
                    raise SystemExit(2)
                res = export_to_sheets(conn, spreadsheet_id=sid, credentials_path=args.sheets_credentials)
                print('Export result:', res)
            finally:
                conn.close()
        elif args.run_all:
            # Run the entire pipeline end-to-end
            initials = get_initials()
            if not initials_is_valid(initials):
                print(f"INVALID INITIALS '{initials}'. Please set INITIALS env var to your initials (e.g., 'NS'). Aborting.")
                raise SystemExit(2)

            run_id = args.run_id or environ.get("SITEMAP_RUN_ID", "run_all_local")
            sources_env = args.sitemap_sources or environ.get("SITEMAP_SOURCES", "docs=https://docs.snowflake.com/en/sitemap.xml")
            sources = parse_key_value_list(sources_env)

            # 1) Extract (bounded by --max-urls)
            conn = get_connection_optional()
            try:
                inserted = run_sitemap_extract(run_id, sources, conn=conn, batch_size=args.batch_size, max_urls=args.max_urls)
                print(f"Sitemap extraction inserted {inserted} rows into run {run_id}")
            finally:
                if conn:
                    conn.close()

            # 2) Consolidate
            conn = require_connection_or_exit()
            try:
                summary = consolidate_run(conn, run_id)
                print('Consolidation summary:', summary)
            finally:
                conn.close()

            # 3) Content fetch (bounded by --max-docs)
            conn = require_connection_or_exit()
            try:
                settings = {}
                if args.max_docs is not None:
                    settings['max_docs'] = args.max_docs
                fetch_summary = run_content_fetch(conn, batch_size=args.content_batch_size, settings=settings)
                print('Content fetch summary:', fetch_summary)
            finally:
                conn.close()

            # 4) Analytics + optional Sheets export
            conn = require_connection_or_exit()
            try:
                from .analytics import run_analytics
                results = run_analytics(conn)
                print('Analytics run complete. Query results:')
                for qid, rows in sorted(results.items()):
                    print(f"--- {qid} ({len(rows)} rows) ---")
                sid = args.sheets_spreadsheet_id or os.environ.get('GOOGLE_SHEETS_SPREADSHEET_ID')
                if sid:
                    try:
                        from .export_sheets import export_to_sheets
                        res = export_to_sheets(conn, spreadsheet_id=sid, credentials_path=args.sheets_credentials)
                        print('Export result:', res)
                    except Exception as exc:
                        print('Export to Sheets failed:', exc)
                else:
                    print('No spreadsheet id provided; skipping Sheets export.')
            finally:
                conn.close()
        else:
            parser.print_help()
