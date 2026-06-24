"""Tokenization module - split text into tokens"""

import re
from typing import List


class BaseTokenizer:
    """Abstract base tokenizer"""

    def tokenize(self, text: str) -> List[str]:
        """Split text into tokens
        
        Args:
            text: Input text to tokenize
            
        Returns:
            List of tokens
        """
        raise NotImplementedError


class WhitespaceTokenizer(BaseTokenizer):
    """Split by whitespace only"""

    def tokenize(self, text: str) -> List[str]:
        return text.split()


class WhitespaceAndPunctuationTokenizer(BaseTokenizer):
    """Split by whitespace and punctuation"""

    def tokenize(self, text: str) -> List[str]:
        tokens = re.split(r'(\s+|(?<=[^\s]),)', text)
        return [t for t in tokens if t and not t.isspace()]


class TokenizerFactory:
    """Factory for creating tokenizers"""

    _tokenizers = {
        'whitespace': WhitespaceTokenizer,
        'whitespace_and_punctuation': WhitespaceAndPunctuationTokenizer,
    }

    @classmethod
    def create(cls, mode: str = 'whitespace') -> BaseTokenizer:
        """Create tokenizer by mode
        
        Args:
            mode: Tokenizer mode name
            
        Returns:
            Tokenizer instance
            
        Raises:
            ValueError: If mode is not supported
        """
        if mode not in cls._tokenizers:
            raise ValueError(f"Unknown tokenizer mode: {mode}. Available: {list(cls._tokenizers.keys())}")
        return cls._tokenizers[mode]()

    @classmethod
    def register(cls, name: str, tokenizer_class: type):
        """Register custom tokenizer
        
        Args:
            name: Tokenizer name
            tokenizer_class: Tokenizer class (must inherit BaseTokenizer)
        """
        if not issubclass(tokenizer_class, BaseTokenizer):
            raise TypeError(f"{tokenizer_class} must inherit BaseTokenizer")
        cls._tokenizers[name] = tokenizer_class
