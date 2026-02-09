"""Small utility helpers shared across the pipeline."""
from __future__ import annotations
from typing import Dict, Optional


def parse_key_value_list(s: Optional[str], default: Optional[str] = None) -> Dict[str, str]:
    """Parse semicolon-separated KEY=VALUE pairs into a dict.

    Example: 'docs=https://docs.snowflake.com/en/sitemap.xml;other=https://other/sitemap.xml'
    Returns: {'docs': 'https://docs.snowflake.com/en/sitemap.xml', 'other': 'https://other/sitemap.xml'}
    """
    if not s or s.strip() == "":
        s = default or ""
    result: Dict[str, str] = {}
    for pair in s.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def require_connection_or_exit():
    """Get a Snowflake connection or exit the process with an error message."""
    from .snowflake import get_connection
    try:
        return get_connection()
    except Exception as exc:
        print("Failed to create Snowflake connection:", exc)
        raise SystemExit(1)
