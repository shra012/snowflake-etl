import pytest
from unittest.mock import MagicMock, patch

from src.docs_pipeline import export_sheets as es


def test_values_from_rows():
    rows = [(1, 'a'), (2, 'b')]
    values = es._values_from_rows(rows)
    assert values[0] == ['col1', 'col2']
    assert values[1] == ['1', 'a']


@patch('src.docs_pipeline.export_sheets._get_sheets_service')
@patch('src.docs_pipeline.export_sheets.run_analytics')
def test_export_to_sheets_creates_and_writes(mock_run_analytics, mock_get_service):
    # mock analytics output
    mock_run_analytics.return_value = {'4a': [("x", 1)], '4b': []}

    # mock sheet service
    mock_service = MagicMock()
    mock_spreadsheets = mock_service.spreadsheets.return_value
    # batchUpdate returns a mock with execute
    mock_spreadsheets.batchUpdate.return_value.execute.return_value = {}
    mock_spreadsheets.values.return_value.update.return_value.execute.return_value = {}
    mock_get_service.return_value = mock_service

    # Call export
    res = es.export_to_sheets(conn=None, spreadsheet_id='sheet123')
    assert res['spreadsheet_id'] == 'sheet123'
    assert '4a' in res['sheets_written']
    assert '4b' in res['sheets_written']
    # ensure update called for 4a and 4b
    assert mock_spreadsheets.values.return_value.update.call_count == 2
