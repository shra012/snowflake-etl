from src.docs_pipeline.analytics import _load_queries


def test_task5_file_contains_sections():
    with open('sql/task5_optimizations.sql') as f:
        s = f.read()
    assert 'Scenario 1' in s
    assert 'Scenario 2' in s
    assert 'Scenario 3' in s
    assert 'COST-EFFICIENT' in s
    assert 'TIME-EFFICIENT' in s
