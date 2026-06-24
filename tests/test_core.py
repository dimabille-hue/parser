"""Test suite for parser_lib

Run with: pytest tests/ -v
"""

import pytest
from parser_lib.core.tokenizer import WhitespaceTokenizer, TokenizerFactory
from parser_lib.core.normalizer import (
    StripStep, RemoveDotsStep, CollapseSpacesStep, NormalizerFactory, NormalizerPipeline
)
from parser_lib.core.validator import NotEmptyValidator, RegexValidator, ValidatorFactory
from parser_lib.core.predicates import StartsUpperPredicate, HasLetterPredicate, PredicateFactory
from parser_lib.core.classifier import Classifier
from parser_lib.utils.distance import levenshtein_distance


class TestTokenizer:
    """Tests for tokenization"""

    def test_whitespace_tokenizer(self):
        tokenizer = WhitespaceTokenizer()
        assert tokenizer.tokenize("hello world") == ["hello", "world"]
        assert tokenizer.tokenize("  a  b  ") == ["a", "b"]
        assert tokenizer.tokenize("") == []

    def test_tokenizer_factory(self):
        tokenizer = TokenizerFactory.create('whitespace')
        assert isinstance(tokenizer, WhitespaceTokenizer)
        
        with pytest.raises(ValueError):
            TokenizerFactory.create('unknown_mode')


class TestNormalizer:
    """Tests for normalization"""

    def test_strip_step(self):
        step = StripStep()
        assert step.apply("  text  ") == "text"
        assert step.apply("") == ""

    def test_remove_dots_step(self):
        step = RemoveDotsStep()
        assert step.apply("1.2.3") == "123"
        assert step.apply("text.with.dots") == "textwithdots"

    def test_collapse_spaces_step(self):
        step = CollapseSpacesStep()
        assert step.apply("a  b   c") == "a b c"
        assert step.apply("  text  ") == "text"

    def test_normalizer_pipeline(self):
        pipeline = NormalizerPipeline([
            StripStep(),
            RemoveDotsStep(),
            CollapseSpacesStep()
        ])
        result = pipeline.normalize("  418. 4.  ")
        assert result == "418 4"

    def test_normalizer_factory_strip(self):
        step = NormalizerFactory.create_step('strip')
        assert isinstance(step, StripStep)

    def test_normalizer_factory_pipeline(self):
        pipeline = NormalizerFactory.create_pipeline(['strip', 'remove_dots'])
        assert pipeline.normalize("  .text.  ") == "text"


class TestValidator:
    """Tests for validation"""

    def test_not_empty_validator(self):
        validator = NotEmptyValidator()
        assert validator.validate("text") is True
        assert validator.validate("") is False
        assert validator.validate("  ") is False

    def test_regex_validator(self):
        validator = RegexValidator(r"^\d{2}:\d{2}$")
        assert validator.validate("59:34") is True
        assert validator.validate("59.34") is False
        assert validator.validate("5934") is False

    def test_validator_factory_not_empty(self):
        validator = ValidatorFactory.create('not_empty')
        assert validator.validate("test") is True
        assert validator.validate("") is False

    def test_validator_factory_regex(self):
        validator = ValidatorFactory.create('regex:^[0-9]+$')
        assert validator.validate("123") is True
        assert validator.validate("12a") is False

    def test_validator_factory_word_count(self):
        validator = ValidatorFactory.create('word_count:2,3')
        assert validator.validate("hello world") is True
        assert validator.validate("hello world test") is True
        assert validator.validate("hello") is False
        assert validator.validate("a b c d") is False


class TestPredicates:
    """Tests for predicates"""

    def test_starts_upper_predicate(self):
        pred = StartsUpperPredicate()
        assert pred("Смирнов.") is True
        assert pred("смирнов.") is False
        assert pred("123") is False

    def test_has_letter_predicate(self):
        pred = HasLetterPredicate()
        assert pred("418а") is True
        assert pred("418") is False
        assert pred("text") is True

    def test_predicate_factory_starts_upper(self):
        pred = PredicateFactory.create('starts_upper')
        assert pred("Text") is True
        assert pred("text") is False

    def test_predicate_factory_regex(self):
        pred = PredicateFactory.create('regex:^[0-9]+$')
        assert pred("123") is True
        assert pred("12a") is False

    def test_predicate_factory_or(self):
        pred = PredicateFactory.create('starts_upper | has_letter')
        assert pred("Text") is True  # starts_upper
        assert pred("text123") is True  # has_letter
        assert pred("123") is False  # neither


class TestLevenshteinDistance:
    """Tests for Levenshtein distance algorithm"""

    def test_identical_strings(self):
        assert levenshtein_distance("фио", "фио") == 0

    def test_one_insertion(self):
        assert levenshtein_distance("кад", "када") == 1

    def test_one_substitution(self):
        assert levenshtein_distance("фио", "фиo") == 1  # Latin 'o'

    def test_completely_different(self):
        assert levenshtein_distance("abc", "xyz") == 3

    def test_empty_strings(self):
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("text", "") == 4
        assert levenshtein_distance("", "text") == 4


class TestClassifier:
    """Tests for trigger classification"""

    @pytest.fixture
    def sample_config(self):
        return {
            'triggers': {
                'фио': {
                    'aliases': ['фио', 'fio'],
                    'search_mode': 'fuzzy',
                },
                'кад': {
                    'aliases': ['кад', 'кадастр'],
                    'search_mode': 'fuzzy',
                }
            },
            'max_distance': 1,
            'require_first_char': True,
            'stop_words': set()
        }

    def test_exact_match(self, sample_config):
        classifier = Classifier(sample_config['triggers'], max_distance=1)
        assert classifier.classify('фио') == 'фио'
        assert classifier.classify('кад') == 'кад'

    def test_fuzzy_match(self, sample_config):
        classifier = Classifier(sample_config['triggers'], max_distance=1)
        # One character difference
        assert classifier.classify('фиo') == 'фио'  # Latin 'o'
        assert classifier.classify('kada') is None  # max_distance exceeded

    def test_stop_words(self):
        config = {
            'triggers': {
                'фио': {'aliases': ['фио'], 'search_mode': 'fuzzy'}
            },
            'max_distance': 1,
            'require_first_char': True,
            'stop_words': {'the', 'фио'}
        }
        classifier = Classifier(config['triggers'], max_distance=1, stop_words=config['stop_words'])
        assert classifier.classify('фио') is None  # Is a stop word
        assert classifier.classify('not_a_stopword') is None

    def test_cache(self, sample_config):
        classifier = Classifier(sample_config['triggers'], max_distance=1)
        # First call
        result1 = classifier.classify('фио')
        # Second call should use cache
        result2 = classifier.classify('фио')
        assert result1 == result2 == 'фио'
        assert len(classifier._cache) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
