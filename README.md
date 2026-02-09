# Snowflake Data Intern Assessment -- ETL Pipeline

## Setup

```bash
cp .env.template .env   # fill in credentials
uv sync                 # install dependencies
uv run pytest -q        # run tests
```

Required `.env` variables:

| Variable | Purpose |
|----------|---------|
| `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` | Snowflake auth |
| `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` | Snowflake target |
| `INITIALS` | Table prefix (e.g. `NS`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Part 1 export sheet |
| `GITHUB_TOKEN` | GitHub personal access token |
| `GITHUB_SHEETS_SPREADSHEET_ID` | Part 2 export sheet |

---

## Part 1: Sitemap URL Analysis

Ingests Snowflake product documentation sitemaps, fetches page content, loads into Snowflake, and runs analytics.

### Project Structure

```
src/docs_pipeline/
    cli.py            # CLI entry point
    config.py         # Environment config and table naming
    sitemap.py        # Sitemap XML extraction
    consolidation.py  # Staging to master merge
    content_fetch.py  # Document content retrieval
    analytics.py      # Task 4 SQL analytics
    export_sheets.py  # Google Sheets export
sql/
    task4_analytics.sql
    task5_optimizations.sql
```

### Usage

```bash
# Full pipeline
python -m src.docs_pipeline.cli --run-all \
  --sitemap-sources "docs=https://docs.snowflake.com/en/sitemap.xml" \
  --sheets-spreadsheet-id <ID>

# Individual steps
python -m src.docs_pipeline.cli --run-sitemap-extract --run-id run_01
python -m src.docs_pipeline.cli --run-consolidate --run-id run_01
python -m src.docs_pipeline.cli --run-content-fetch
python -m src.docs_pipeline.cli --run-analytics
python -m src.docs_pipeline.cli --export-sheets --sheets-spreadsheet-id <ID>
```

---

## Part 2: GitHub Contributor Analytics

Ingests contributor activity from the GitHub REST API for `apache/airflow`, computes weighted scores and tiers, and exports results to Google Sheets.

### Project Structure

```
src/github_pipeline/
    config.py         # Token and credential loading from .env
    ingestion.py      # Paginated GitHub API fetching with retry
    transformation.py # Scoring, tiering, ranking
    export_sheets.py  # Google Sheets export
github_pipeline_notebook.ipynb  # Orchestration notebook
```

### Scoring

```
raw_score = (commits x 5) + (prs x 10) + (comments x 2) + (reviews x 3)
score     = min(raw_score, 100)
```

### Tier Definitions

| Tier | Criteria |
|------|----------|
| core | commits + prs >= 20 |
| active | commits + prs >= 5 |
| contributor | commits + prs >= 1 |
| observer | commits + prs = 0 |

### Usage

Run `github_pipeline_notebook.ipynb` end-to-end. The notebook calls:

1. `ingestion.run_ingestion()` -- fetches commits, PRs, comments, issues, reviews
2. `transformation.process_contributors(data)` -- builds scored/ranked DataFrame
3. `export_sheets.export_to_sheets(df, spreadsheet_id)` -- writes to Google Sheets

---

## Tests

```bash
uv run pytest -q                     # all tests
uv run pytest tests/test_github_*.py # Part 2 only
```

## Notes

- Never commit `.env` or `src/resources/gcp.json`. Both are in `.gitignore`.
- The `INITIALS` variable prefixes all Snowflake table names to avoid collisions.
- GitHub ingestion defaults to 1,000 rows per endpoint (10 pages x 100/page).
