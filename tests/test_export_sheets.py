
from unittest.mock import MagicMock, patch
import pytest
from src.docs_pipeline.export_sheets import export_to_sheets

@patch('src.docs_pipeline.export_sheets._get_sheets_service')
@patch('src.docs_pipeline.export_sheets.run_analytics')
def test_export_to_sheets_flow(mock_run_analytics, mock_get_service):
    # Setup mocks
    mock_conn = MagicMock()
    mock_service = MagicMock()
    mock_sheet_service = MagicMock()
    mock_spreadsheets = MagicMock()
    
    mock_get_service.return_value = mock_service
    mock_service.spreadsheets.return_value = mock_spreadsheets
    
    # Mock spreadsheet get (metadata)
    mock_get = MagicMock()
    mock_spreadsheets.get.return_value = mock_get
    mock_get.execute.return_value = {
        'sheets': [
            {'properties': {'title': '4a'}} # 4a exists, 4b does not
        ]
    }

    
    # Mock analytics results with columns
    mock_run_analytics.return_value = {
        '4a': {
            'columns': ['SOURCE', 'COUNT'],
            'rows': [('s1', 10), ('s2', 20)]
        },
        '4b': {
            'columns': ['MONTH', 'COUNT'],
            'rows': [] # Empty result
        }
    }

    # Execute
    res = export_to_sheets(mock_conn, "test_spreadsheet_id")

    # Verify run_analytics called
    mock_run_analytics.assert_called_once_with(mock_conn)

    # Verify sheet creation attempts (batchUpdate) for only 4b (since 4a exists)
    assert mock_spreadsheets.batchUpdate.call_count == 1
    call_args_create = mock_spreadsheets.batchUpdate.call_args
    _, kwargs_create = call_args_create
    assert kwargs_create['body']['requests'][0]['addSheet']['properties']['title'] == '4b'

    
    # Verify data updates
    assert mock_spreadsheets.values.return_value.update.call_count == 2
    
    # Check first update (4a)
    call_args_4a = mock_spreadsheets.values.return_value.update.call_args_list[0]
    _, kwargs_4a = call_args_4a
    assert kwargs_4a['range'] == "'4a'!A1"
    assert kwargs_4a['body']['values'] == [['SOURCE', 'COUNT'], ['s1', '10'], ['s2', '20']]

    # Check second update (4b) - should just be headers or empty marker?
    # Logic says: if not values (i.e. empty rows AND empty cols), write 'no results'.
    # But here we have columns, so it should write headers.
    call_args_4b = mock_spreadsheets.values.return_value.update.call_args_list[1]
    _, kwargs_4b = call_args_4b
    assert kwargs_4b['range'] == "'4b'!A1"
    assert kwargs_4b['body']['values'] == [['MONTH', 'COUNT']]

    assert res['spreadsheet_id'] == "test_spreadsheet_id"
    assert res['sheets_written'] == ['4a', '4b']
