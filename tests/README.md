# Parser Library Tests

This directory contains the test suite for the parser library.

## Running Tests

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_core.py -v

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=parser_lib --cov-report=html
```

## Test Structure

- **test_core.py** - Tests for tokenizer, normalizer, validator, predicates, classifier, and distance algorithms
- **test_config.py** - Tests for configuration loading and validation
- **test_exporters.py** - Tests for CSV and JSON export functionality

## Test Coverage Goals

- Tokenization: 100%
- Normalization: 95%+
- Validation: 95%+
- Predicates: 100%
- Classifier: 90%+
- Configuration: 90%+
- Exporters: 90%+
