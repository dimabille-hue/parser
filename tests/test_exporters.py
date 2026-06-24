"""Output exporter tests"""

import pytest
from parser_lib.outputs.csv_exporter import CSVExporter
from parser_lib.outputs.json_exporter import JSONExporter
import json
import csv
import io


class TestCSVExporter:
    """Tests for CSV export"""

    @pytest.fixture
    def sample_records(self):
        return [
            {"id": "1", "name": "Иванов", "err": ""},
            {"id": "2", "name": "Петров", "err": "errDUP"},
        ]

    def test_escape_formula_injection(self):
        # Excel formula injection prevention
        assert CSVExporter._escape_formula("=SUM(A1:A10)") == "'=SUM(A1:A10)"
        assert CSVExporter._escape_formula("+sum(1+1)") == "'+sum(1+1)"
        assert CSVExporter._escape_formula("normal text") == "normal text"

    def test_export_to_bytes(self, sample_records):
        columns = ["id", "name"]
        result = CSVExporter.export(sample_records, columns)
        
        # Should be bytes with UTF-8 BOM
        assert isinstance(result, bytes)
        assert result.startswith(b'\xef\xbb\xbf')  # UTF-8 BOM
        
        # Decode and verify content
        text = result.decode('utf-8-sig')
        lines = text.strip().split('\n')
        assert len(lines) == 3  # Header + 2 records
        assert 'id' in lines[0]
        assert 'name' in lines[0]

    def test_export_includes_error_column(self, sample_records):
        columns = ["id", "name"]
        result = CSVExporter.export(sample_records, columns, include_error_column=True)
        text = result.decode('utf-8-sig')
        assert 'err' in text
        assert 'errDUP' in text


class TestJSONExporter:
    """Tests for JSON export"""

    @pytest.fixture
    def sample_records(self):
        return [
            {"id": "1", "name": "Иванов"},
            {"id": "2", "name": "Петров"},
        ]

    def test_export_to_bytes(self, sample_records):
        columns = ["id", "name"]
        result = JSONExporter.export(sample_records, columns)
        
        assert isinstance(result, bytes)
        data = json.loads(result.decode('utf-8'))
        
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "1"
        assert data[0]["name"] == "Иванов"

    def test_export_with_missing_fields(self):
        records = [{"id": "1"}, {"id": "2", "name": "test"}]
        columns = ["id", "name"]
        result = JSONExporter.export(records, columns)
        data = json.loads(result.decode('utf-8'))
        
        # Missing fields should be empty strings
        assert data[0]["name"] == ""
        assert data[1]["name"] == "test"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
