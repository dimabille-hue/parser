"""Validation module - check extracted values"""

import re
from typing import Callable, Optional


class BaseValidator:
    """Abstract validator"""

    def validate(self, value: str) -> bool:
        """Check if value is valid
        
        Args:
            value: Value to validate
            
        Returns:
            True if valid, False otherwise
        """
        raise NotImplementedError

    def get_error_message(self) -> str:
        """Get error message for failed validation
        
        Returns:
            Error message
        """
        raise NotImplementedError


class NotEmptyValidator(BaseValidator):
    """Check that value is not empty"""

    def validate(self, value: str) -> bool:
        return bool(value.strip())

    def get_error_message(self) -> str:
        return "Value is empty"


class RegexValidator(BaseValidator):
    """Validate using regex pattern"""

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.regex = re.compile(pattern)

    def validate(self, value: str) -> bool:
        return bool(self.regex.fullmatch(value))

    def get_error_message(self) -> str:
        return f"Value does not match pattern: {self.pattern}"


class WordCountValidator(BaseValidator):
    """Validate word count range"""

    def __init__(self, min_words: int = 0, max_words: int = 1000):
        self.min_words = min_words
        self.max_words = max_words

    def validate(self, value: str) -> bool:
        word_count = len(value.split())
        return self.min_words <= word_count <= self.max_words

    def get_error_message(self) -> str:
        return f"Word count must be between {self.min_words} and {self.max_words}"


class LengthValidator(BaseValidator):
    """Validate string length"""

    def __init__(self, min_length: int = 0, max_length: int = 1000):
        self.min_length = min_length
        self.max_length = max_length

    def validate(self, value: str) -> bool:
        return self.min_length <= len(value) <= self.max_length

    def get_error_message(self) -> str:
        return f"Length must be between {self.min_length} and {self.max_length}"


class ChoicesValidator(BaseValidator):
    """Validate value is in list of choices"""

    def __init__(self, choices: list, case_sensitive: bool = True):
        self.choices = choices if case_sensitive else [c.lower() for c in choices]
        self.case_sensitive = case_sensitive

    def validate(self, value: str) -> bool:
        check_value = value if self.case_sensitive else value.lower()
        return check_value in self.choices

    def get_error_message(self) -> str:
        return f"Value must be one of: {', '.join(self.choices)}"


class ValidatorFactory:
    """Factory for creating validators"""

    @classmethod
    def create(cls, rule: str) -> BaseValidator:
        """Create validator from rule definition
        
        Args:
            rule: Rule definition (e.g., 'not_empty', 'regex:^[0-9]+$', 'word_count:2,5')
            
        Returns:
            Validator instance
            
        Raises:
            ValueError: If rule is not recognized
        """
        if rule == 'not_empty':
            return NotEmptyValidator()
        
        if rule.startswith('regex:'):
            pattern = rule[6:].strip()
            return RegexValidator(pattern)
        
        if rule.startswith('word_count:'):
            parts = rule.split(':')[1]
            try:
                min_words, max_words = map(int, parts.split(','))
                return WordCountValidator(min_words, max_words)
            except ValueError:
                raise ValueError(f"Invalid word_count format: {rule}")
        
        if rule.startswith('length:'):
            parts = rule.split(':')[1]
            try:
                min_len, max_len = map(int, parts.split(','))
                return LengthValidator(min_len, max_len)
            except ValueError:
                raise ValueError(f"Invalid length format: {rule}")
        
        if rule.startswith('choices:'):
            choices_str = rule.split(':', 1)[1]
            choices = [c.strip() for c in choices_str.split(',')]
            return ChoicesValidator(choices)
        
        raise ValueError(f"Unknown validation rule: {rule}")
