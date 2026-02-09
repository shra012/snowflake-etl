"""Configuration and helpers for the docs pipeline.

Loads environment variables (optionally from a .env file) and provides
helpers for building the required `CANDIDATE_{INITIALS}_...` table names.

See `.env.template` for the list of expected environment variables.
"""
from __future__ import annotations
import os
from typing import Dict, Optional

# Load .env automatically if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional; if not installed the environment variables must be set externally
    pass

def get_initials() -> str:
    """Return the `INITIALS` env var (trimmed, uppercase). Defaults to 'NS'."""
    return os.environ.get("INITIALS", "NS").strip().upper()


def initials_is_valid(initials: str) -> bool:
    """Return True if initials look valid (1-3 uppercase letters and not a known placeholder)."""
    import re

    if not initials:
        return False
    # Reserve some placeholders to avoid accidental writes. Replaced 'NS' with 'ZZ' so 'NS' can be used when intended.
    if initials in {"TEST", "ZZ"}:
        return False
    return bool(re.fullmatch(r"[A-Z]{1,3}", initials))


def tbl(table_name: str) -> str:
    """Return fully prefixed table name required by the prompt (reads `INITIALS` at call time)."""
    initials = get_initials()
    return f"CANDIDATE_{initials}_{table_name}"


def get_snowflake_params() -> Dict[str, Optional[str]]:
    """Return a dict of Snowflake connection params read from env vars.

    Expected env vars (see `.env.template`):
      - SNOWFLAKE_ACCOUNT
      - SNOWFLAKE_USER
      - SNOWFLAKE_PASSWORD (or key auth)
      - SNOWFLAKE_WAREHOUSE
      - SNOWFLAKE_DATABASE
      - SNOWFLAKE_SCHEMA
    """
    return {
        "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
        "user": os.environ.get("SNOWFLAKE_USER"),
        "password": os.environ.get("SNOWFLAKE_PASSWORD"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"),
        "database": os.environ.get("SNOWFLAKE_DATABASE"),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA"),
        "role": os.environ.get("SNOWFLAKE_ROLE"),
    }
