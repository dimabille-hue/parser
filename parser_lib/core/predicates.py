"""Predicate module - token classification functions"""

import re
from typing import Callable


class BasePredicate:
    """Abstract predicate for token classification"""

    def __call__(self, token: str) -> bool:
        """Check if token matches predicate
        
        Args:
            token: Token to check
            
        Returns:
            True if matches, False otherwise
        """
        raise NotImplementedError


class StartsUpperPredicate(BasePredicate):
    """Token starts with uppercase letter (not digit)"""

    def __call__(self, token: str) -> bool:
        t = token.strip(".,;:!?()[]{}").lower()
        if not t or any(ch.isdigit() for ch in t):
            return False
        return t[0].isupper()


class HasLetterPredicate(BasePredicate):
    """Token contains at least one letter"""

    def __call__(self, token: str) -> bool:
        return any(ch.isalpha() for ch in token)


class LooksLikeNumberPredicate(BasePredicate):
    """Token consists of digits, letters, dots and colons"""

    def __call__(self, token: str) -> bool:
        clean = token.replace(' ', '')
        return bool(clean) and bool(re.fullmatch(r'[0-9а-яёA-Z.:]+', clean, re.IGNORECASE))


class IsPartOfNumberPredicate(BasePredicate):
    """Same as above + contains digit or dot/colon"""

    def __call__(self, token: str) -> bool:
        if not LooksLikeNumberPredicate()(token):
            return False
        return any(ch.isdigit() or ch in '.:' for ch in token)


class AnyPredicate(BasePredicate):
    """Any non-empty token"""

    def __call__(self, token: str) -> bool:
        return bool(token.strip())


class RegexPredicate(BasePredicate):
    """Match against regex pattern"""

    def __init__(self, pattern: str):
        self.pattern = re.compile(pattern)

    def __call__(self, token: str) -> bool:
        return bool(self.pattern.search(token))


class OrPredicate(BasePredicate):
    """Logical OR of predicates"""

    def __init__(self, predicates: list):
        self.predicates = predicates

    def __call__(self, token: str) -> bool:
        return any(p(token) for p in self.predicates)


class PredicateFactory:
    """Factory for creating predicates"""

    _predicates = {
        'starts_upper': StartsUpperPredicate,
        'has_letter': HasLetterPredicate,
        'looks_like_number_colon_dot': LooksLikeNumberPredicate,
        'is_part_of_number_colon_dot': IsPartOfNumberPredicate,
        'any': AnyPredicate,
    }

    @classmethod
    def create(cls, expr: str) -> BasePredicate:
        """Create predicate from expression
        
        Args:
            expr: Expression (e.g., 'starts_upper', 'regex:^[A-Z]', 'starts_upper | has_letter')
            
        Returns:
            Predicate instance
            
        Raises:
            ValueError: If expression is not recognized
        """
        # Handle OR expressions
        if '|' in expr:
            parts = [p.strip() for p in expr.split('|')]
            predicates = [cls.create(p) for p in parts]
            return OrPredicate(predicates)
        
        expr = expr.strip()
        
        # Handle regex
        if expr.startswith('regex:'):
            pattern = expr[6:].strip()
            return RegexPredicate(pattern)
        
        # Handle built-in predicates
        if expr in cls._predicates:
            return cls._predicates[expr]()
        
        raise ValueError(f"Unknown predicate: {expr}")

    @classmethod
    def register(cls, name: str, predicate_class: type):
        """Register custom predicate
        
        Args:
            name: Predicate name
            predicate_class: Predicate class (must inherit BasePredicate)
        """
        if not issubclass(predicate_class, BasePredicate):
            raise TypeError(f"{predicate_class} must inherit BasePredicate")
        cls._predicates[name] = predicate_class
