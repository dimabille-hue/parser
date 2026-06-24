"""Configuration loader and validator tests"""

import pytest
import json
import tempfile
from pathlib import Path
from parser_lib.config.loader import ConfigLoader


class TestConfigLoader:
    """Tests for configuration loading and validation"""

    @pytest.fixture
    def valid_config(self):
        return {
            "parser_name": "Test Parser",
            "version": "1.0",
            "csv_columns": ["field1", "field2"],
            "triggers": {
                "trigger1": {
                    "aliases": ["alias1"],
                    "search_mode": "fuzzy"
                }
            }
        }

    @pytest.fixture
    def temp_config_file(self, valid_config):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(valid_config, f)
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink()

    def test_load_json(self, temp_config_file, valid_config):
        loaded = ConfigLoader.load_json(temp_config_file)
        assert loaded == valid_config

    def test_load_json_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load_json('/nonexistent/path/config.json')

    def test_validate_basic_valid(self, valid_config):
        errors = ConfigLoader.validate_basic(valid_config)
        assert len(errors) == 0

    def test_validate_basic_missing_parser_name(self, valid_config):
        del valid_config["parser_name"]
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("parser_name" in e for e in errors)

    def test_validate_basic_missing_csv_columns(self, valid_config):
        del valid_config["csv_columns"]
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("csv_columns" in e for e in errors)

    def test_validate_basic_missing_triggers(self, valid_config):
        del valid_config["triggers"]
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("triggers" in e for e in errors)

    def test_validate_basic_empty_triggers(self, valid_config):
        valid_config["triggers"] = {}
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("non-empty" in e for e in errors)

    def test_validate_basic_invalid_parser_name_type(self, valid_config):
        valid_config["parser_name"] = 123
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("parser_name" in e and "string" in e for e in errors)

    def test_validate_basic_invalid_csv_columns_type(self, valid_config):
        valid_config["csv_columns"] = "not_a_list"
        errors = ConfigLoader.validate_basic(valid_config)
        assert any("csv_columns" in e for e in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
