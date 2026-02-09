import os

from src.docs_pipeline import config


def test_tbl_with_initials(monkeypatch):
    monkeypatch.setenv("INITIALS", "ZZ")
    import importlib
    importlib.reload(config)

    assert config.tbl("DOCS_MASTER") == "CANDIDATE_ZZ_DOCS_MASTER"
