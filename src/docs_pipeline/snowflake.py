"""Snowflake connection helpers."""
from __future__ import annotations
from typing import Any, Dict, Optional

from .config import get_snowflake_params

try:
    import snowflake.connector
except Exception:
    snowflake = None  # graceful if the connector isn't installed yet


def get_connection(**overrides: Any):
    """Return a Snowflake connection using env vars (or overrides).

    Example overrides: account='...', user='...', password='...'
    """
    params = get_snowflake_params()
    params.update({k: v for k, v in overrides.items() if v is not None})

    if snowflake is None:
        raise RuntimeError("snowflake-connector-python is not installed in the environment")

    # Keep a minimal set of kwargs for snowflake.connector.connect
    conn_kwargs: Dict[str, Optional[Any]] = {
        "account": params.get("account"),
        "user": params.get("user"),
        "password": params.get("password"),
        "warehouse": params.get("warehouse"),
        "database": params.get("database"),
        "schema": params.get("schema"),
        "role": params.get("role"),
    }

    # Remove None values
    conn_kwargs = {k: v for k, v in conn_kwargs.items() if v is not None}

    return snowflake.connector.connect(**conn_kwargs)


def get_connection_optional(**overrides: Any):
    """Attempt to get a Snowflake connection but return None on failure.

    Useful for CLI operations where the connection is optional (e.g., preview runs).
    """
    try:
        return get_connection(**overrides)
    except Exception:
        return None


def execute(conn, sql: str, params: Optional[Dict[str, Any]] = None):
    """Execute SQL and return cursor/fetchall result (if any)."""
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        try:
            return cur.fetchall()
        except Exception:
            return None


def test_connection(**overrides: Any) -> Dict[str, Any]:
    """Run a quick Snowflake connection diagnostic.

    Returns a dict with keys:
      - ok: bool
      - details: dict (version, pandas_available, pyarrow_available)
      - error: error string if failed
      - traceback: full traceback when available

    Accepts the same overrides as `get_connection` to pass explicit creds.
    """
    params = get_snowflake_params()
    missing = [k for k in ("account", "user", "password") if not params.get(k) and not overrides.get(k)]

    result: Dict[str, Any] = {"ok": False, "details": {}, "error": None}

    if missing:
        result["error"] = f"Missing required credentials: {', '.join(missing)}"
        return result

    # Check local availability of pandas/pyarrow (useful for pandas fetch API)
    try:
        import pandas as _pd  # type: ignore
        import pyarrow as _pa  # type: ignore
        result["details"]["pandas_available"] = True
        result["details"]["pyarrow_available"] = True
    except Exception:
        result["details"]["pandas_available"] = False
        result["details"]["pyarrow_available"] = False

    try:
        conn = get_connection(**overrides)
        with conn.cursor() as cur:
            cur.execute("select current_version()")
            ver = cur.fetchone()
        conn.close()
        result["ok"] = True
        result["details"]["version"] = ver
    except Exception as exc:  # capture and return diagnostics
        import traceback

        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    return result
