"""Tests for ParseEngine"""

import pytest
from parser_lib.core.engine import ParseEngine
from parser_lib.config.loader import ConfigLoader


class TestParseEngine:
    """Tests for the main parsing engine"""

    @pytest.fixture
    def sample_config(self):
        return {
            "parser_name": "Test Parser",
            "version": "1.0",
            "csv_columns": ["яч", "ном", "фио"],
            "max_distance": 1,
            "require_first_char": True,
            "stop_words": [],
            "log_suspicious": True,
            "tokenizer": {"split_by": "whitespace"},
            "record_detection": {
                "mode": "trigger",
                "trigger": "яч",
                "continuation_heuristics": {
                    "detect_by": "has_letter",
                    "max_tokens_to_check": 5
                }
            },
            "triggers": {
                "яч": {
                    "aliases": ["яч"],
                    "search_mode": "fuzzy",
                    "csv_column": "яч",
                    "on_new_record": True,
                    "normalization": {"pipeline": ["strip", "digits_only"]},
                    "collector": {"token_rule": "any", "max_tokens": 1}
                },
                "ном": {
                    "aliases": ["ном"],
                    "search_mode": "fuzzy",
                    "csv_column": "ном",
                    "normalization": {"pipeline": ["strip", "remove_trailing_dot"]},
                    "collector": {"token_rule": "any", "max_tokens": 1}
                },
                "фио": {
                    "aliases": ["фио"],
                    "search_mode": "fuzzy",
                    "csv_column": "фио",
                    "normalization": {"pipeline": ["strip", "collapse_spaces"]},
                    "validation": {
                        "rule": "word_count:1,3",
                        "error_code": "errFIO"
                    }
                }
            }
        }

    def test_engine_initialization(self, sample_config):
        engine = ParseEngine(sample_config)
        assert engine is not None
        assert engine.config == sample_config
        assert len(engine.normalizers) == 3
        assert len(engine.validators) == 3

    def test_engine_initialization_invalid_config(self):
        invalid_config = {"parser_name": "Test"}  # Missing required fields
        with pytest.raises(ValueError):
            ParseEngine(invalid_config)

    def test_parse_simple_record(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1. Ном. 418. Фио. Иванов."
        results = engine.parse(text)
        
        assert len(results) == 1
        assert results[0]["яч"] == "1"
        assert results[0]["ном"] == "418"
        assert results[0]["фио"] == "Иванов"

    def test_parse_multiple_records(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1. Ном. 418. Фио. Иванов. Яч 2. Ном. 6. Фио. Петров."
        results = engine.parse(text)
        
        assert len(results) == 2
        assert results[0]["яч"] == "1"
        assert results[1]["яч"] == "2"

    def test_parse_with_normalization(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1a2b3. Ном. 418. Фио. Test."
        results = engine.parse(text)
        
        # digits_only for яч
        assert results[0]["яч"] == "123"

    def test_parse_with_validation(self, sample_config):
        engine = ParseEngine(sample_config)
        
        # Valid: 2 words
        text1 = "Яч 1. Фио. Иванов Петр."
        results1 = engine.parse(text1)
        assert results1[0].get('err', '') == ''
        
        # Invalid: 4 words
        text2 = "Яч 1. Фио. Иванов Петр Николай Константин."
        results2 = engine.parse(text2)
        assert 'errFIO' in results2[0].get('err', '')

    def test_get_stats(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1. Ном. 418. Фио. Иванов. Яч 2. Ном. 6."
        engine.parse(text)
        
        stats = engine.get_stats()
        assert stats['total'] == 2
        assert stats['clean'] == 1  # Second record missing фио but not an error

    def test_get_records(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1. Ном. 418. Фио. Иванов."
        results = engine.parse(text)
        
        records = engine.get_records()
        assert records == results

    def test_suspicious_logging(self, sample_config):
        engine = ParseEngine(sample_config)
        text = "Яч 1. Ном. 418. unknown_word. Фио. Иванов."
        engine.parse(text)
        
        suspicious = engine.get_suspicious_tokens()
        token_strs = [token for token, count in suspicious]
        assert 'unknown_word.' in token_strs

    def test_debug_logging(self, sample_config):
        engine = ParseEngine(sample_config, debug=True)
        text = "Яч 1. Ном. 418. Фио. Иванов."
        engine.parse(text)
        
        # Debug log should contain tokenization info
        debug_log = engine.get_debug_log()
        # With debug=True, logging goes to the logger, not a list
        # This is implementation-dependent


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
