"""DDL for GitHub raw data tables in Snowflake.

Tables follow the CANDIDATE_{INITIALS}_ naming convention from docs_pipeline.
Each table stores the full API response as VARIANT plus extracted key fields
used for deduplication and resume.
"""
from __future__ import annotations

from src.docs_pipeline.config import tbl


def get_ddl() -> str:
    """Return CREATE TABLE IF NOT EXISTS statements for all GitHub raw tables."""
    return f"""
-- GitHub Raw Data Tables

CREATE TABLE IF NOT EXISTS {tbl('GH_RAW_COMMITS')} (
    SHA             VARCHAR(40)     NOT NULL PRIMARY KEY,
    AUTHOR_NAME     VARCHAR(500),
    AUTHOR_LOGIN    VARCHAR(200),
    COMMITTED_DATE  TIMESTAMP_NTZ,
    MESSAGE         VARCHAR(5000),
    RAW_JSON        VARIANT         NOT NULL,
    LOADED_AT       TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {tbl('GH_RAW_PULLS')} (
    NUMBER          INTEGER         NOT NULL PRIMARY KEY,
    AUTHOR_LOGIN    VARCHAR(200),
    STATE           VARCHAR(20),
    TITLE           VARCHAR(2000),
    UPDATED_AT      TIMESTAMP_NTZ,
    CREATED_AT      TIMESTAMP_NTZ,
    RAW_JSON        VARIANT         NOT NULL,
    LOADED_AT       TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {tbl('GH_RAW_PR_COMMENTS')} (
    ID              INTEGER         NOT NULL PRIMARY KEY,
    AUTHOR_LOGIN    VARCHAR(200),
    PULL_REQUEST_URL VARCHAR(1000),
    UPDATED_AT      TIMESTAMP_NTZ,
    CREATED_AT      TIMESTAMP_NTZ,
    BODY            VARCHAR(10000),
    RAW_JSON        VARIANT         NOT NULL,
    LOADED_AT       TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {tbl('GH_RAW_ISSUES')} (
    ID              INTEGER         NOT NULL PRIMARY KEY,
    AUTHOR_LOGIN    VARCHAR(200),
    STATE           VARCHAR(20),
    TITLE           VARCHAR(2000),
    UPDATED_AT      TIMESTAMP_NTZ,
    CREATED_AT      TIMESTAMP_NTZ,
    RAW_JSON        VARIANT         NOT NULL,
    LOADED_AT       TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {tbl('GH_RAW_REVIEWS')} (
    ID              INTEGER         NOT NULL,
    PULL_NUMBER     INTEGER         NOT NULL,
    AUTHOR_LOGIN    VARCHAR(200),
    STATE           VARCHAR(50),
    SUBMITTED_AT    TIMESTAMP_NTZ,
    RAW_JSON        VARIANT         NOT NULL,
    LOADED_AT       TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (ID, PULL_NUMBER)
);
"""


def apply_ddl(conn) -> None:
    """Execute DDL statements against the provided Snowflake connection."""
    ddl = get_ddl()
    with conn.cursor() as cur:
        # Debug context
        cur.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
        db, schema = cur.fetchone()
        print(f"Applying DDL in {db}.{schema}...")


        # Remove comment lines first to avoid skipping valid SQL mixed with comments
        clean_ddl = "\n".join(
            line for line in ddl.splitlines() 
            if not line.strip().startswith("--")
        )

        for statement in clean_ddl.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    print(f"Executing: {stmt[:50]}...")
                    cur.execute(stmt)
                except Exception as e:
                    print(f"Error executing DDL: {e}")
                    raise
        
        # Verify creation
        cur.execute("SHOW TABLES LIKE 'CANDIDATE_%_GH_RAW_%'")
        tables = [row[1] for row in cur.fetchall()]
        print(f"Existing tables in {schema}: {tables}")

    print("GitHub raw tables created/verified.")


def drop_tables(conn) -> None:
    """Drop all GitHub raw tables. Use before apply_ddl for a clean slate."""
    table_suffixes = [
        "GH_RAW_COMMITS", "GH_RAW_PULLS", "GH_RAW_PR_COMMENTS",
        "GH_RAW_ISSUES", "GH_RAW_REVIEWS",
    ]
    with conn.cursor() as cur:
        for suffix in table_suffixes:
            table_name = tbl(suffix)
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")
            print(f"  Dropped {table_name}")
    print("All GitHub raw tables dropped.")
