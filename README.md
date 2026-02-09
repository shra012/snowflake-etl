# Product Documentation Pipeline

Minimal project skeleton for the Snowflake docs pipeline take-home.

Quick start (macOS):

1. Create a virtual environment:

   python3 -m venv .venv

2. Activate it:

   source .venv/bin/activate

3. Upgrade pip and install the project dependencies:

   python -m pip install --upgrade pip
   pip install -e .[dev]

   Optional: install the data extras required for Snowflake's pandas fetch API (provides `pandas` and `pyarrow`):

   pip install -e .[data]

4. Copy `.env.template` to `.env` and fill in Snowflake and other credentials.

5. Run tests:

   pytest -q

Minimal CLI usage (quick checks & full pipeline)

Overview: run individual steps or a single `--run-all` to perform extraction → consolidation → fetch → analytics → (optional) Sheets export.

Common flags:
- `--run-id <id>` — attach an id to sitemap staging and consolidation runs
- `--sitemap-sources "key=https://...;key2=https://..."` — provide multiple sitemap sources
- `--batch-size <n>` — staging insert batch size (default 500)
- `--max-urls <n>` — limit sitemap extraction for smoke runs
- `--content-batch-size <n>` — number of docs processed per batch in fetch (default 100)
- `--max-docs <n>` — limit docs fetched for smoke runs

Commands (minimal usage):

- Print DDL for tables (verify table names):

  python -m src.docs_pipeline.cli --create-tables

- Apply DDL to Snowflake (CAUTION: runs SQL against your account):

  python -m src.docs_pipeline.cli --apply-tables --yes

- Run a quick Snowflake diagnostic (prints version and pandas/pyarrow availability):

  python -m src.docs_pipeline.cli --test-connection

- Extract sitemaps and insert to SITEMAP_STAGING (provide run id and optional sources):

  python -m src.docs_pipeline.cli --run-sitemap-extract --run-id run_20260101 --sitemap-sources "docs=https://docs.snowflake.com/en/sitemap.xml"

  Smoke extract (limit urls):

  python -m src.docs_pipeline.cli --run-sitemap-extract --run-id smoke_run --sitemap-sources "docs=https://docs.snowflake.com/en/sitemap.xml;other=https://other-docs.snowflake.com/en/sitemap.xml" --max-urls 500

- Consolidate staging into DOCS_MASTER (idempotent MERGE):

  python -m src.docs_pipeline.cli --run-consolidate --run-id run_20260101

- Fetch document content and update DOCUMENT_CONTENT:

  python -m src.docs_pipeline.cli --run-content-fetch --content-batch-size 100

  Smoke fetch (limit docs):

  python -m src.docs_pipeline.cli --run-content-fetch --content-batch-size 50 --max-docs 200

- Run Task 4 analytics and print results:

  python -m src.docs_pipeline.cli --run-analytics

- Export analytics to Google Sheets (requires `GOOGLE_APPLICATION_CREDENTIALS` or `--sheets-credentials` and the sheet ID):

  python -m src.docs_pipeline.cli --export-sheets --sheets-spreadsheet-id <SPREADSHEET_ID>

  Or run with explicit creds path:

  python -m src.docs_pipeline.cli --export-sheets --sheets-spreadsheet-id <SPREADSHEET_ID> --sheets-credentials /path/to/creds.json

- Run the entire pipeline end-to-end (extract → consolidate → fetch → analytics → export):

  python -m src.docs_pipeline.cli --run-all --sitemap-sources "docs=https://docs.snowflake.com/en/sitemap.xml;other=https://other-docs.snowflake.com/en/sitemap.xml" --max-urls 500 --max-docs 200 --sheets-spreadsheet-id <SPREADSHEET_ID>

Notes & safety tips
- The CLI validates `INITIALS` env var to avoid accidental writes to placeholder tables — set `INITIALS` to your initials (e.g., `INITIALS=JD`).
- Provide credentials via `.env` or environment variables and never commit `.env` or service account JSON into git. The repository `.gitignore` already excludes `.env` and `src/resources/gcp.json`.
- For long/full runs prefer conservative `--content-batch-size` and `--max-docs` and enable retry/timeout config as needed.

See `src/docs_pipeline/cli.py` for exact flag names and behavior. 💡
