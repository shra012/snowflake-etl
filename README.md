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

Minimal CLI usage (quick checks):

- Print DDL for tables (verify table names):

  python -m src.docs_pipeline.cli --create-tables

- Run a quick Snowflake diagnostic (prints version and pandas/pyarrow availability):

  python -m src.docs_pipeline.cli --test-connection

- Apply DDL to your Snowflake account (CAUTION: runs SQL against your account). Requires both flags to run:

  python -m src.docs_pipeline.cli --apply-tables --yes

Notes:
- The `--apply-tables` behaviour will not run unless `--yes` is supplied (suitable for automation/CI when used with environment-based credentials).
- Environment variables are loaded automatically if `python-dotenv` is installed.
- See `src/docs_pipeline/config.py` for the `tbl()` helper used to build the required `CANDIDATE_{INITIALS}_*` table names.
