"""Classifier module - assign tokens to triggers"""

from typing import Optional, Dict, Set
from parser_lib.utils.distance import levenshtein_distance


class Classifier:
    """Token classifier for trigger matching"""

    def __init__(
        self,
        triggers: Dict[str, dict],
        max_distance: int = 1,
        require_first_char: bool = True,
        stop_words: Optional[Set[str]] = None,
        debug: bool = False
    ):
        """Initialize classifier
        
        Args:
            triggers: Dict of trigger configurations
            max_distance: Max Levenshtein distance for fuzzy matching
            require_first_char: Require first char match in fuzzy mode
            stop_words: Set of stop words to ignore
            debug: Enable debug logging
        """
        self.triggers = triggers
        self.max_distance = max_distance
        self.require_first_char = require_first_char
        self.stop_words = stop_words or set()
        self.debug = debug
        self._cache: Dict[str, Optional[str]] = {}

    def classify(self, raw_token: str) -> Optional[str]:
        """Classify token to trigger name or None
        
        Args:
            raw_token: Input token
            
        Returns:
            Trigger name or None if not matched
        """
        # Check cache
        if raw_token in self._cache:
            return self._cache[raw_token]

        # Clean token
        clean = "".join(ch for ch in raw_token.lower() if ch.isalpha())
        
        # Handle empty and stop words
        if not clean or clean in self.stop_words:
            self._cache[raw_token] = None
            return None

        best_trigger = None
        best_distance = 999

        for tname, trig in self.triggers.items():
            mode = trig.get('search_mode', 'fuzzy')
            aliases = trig.get('aliases', [])

            # Exact match
            if mode == 'exact':
                if clean in [a.lower() for a in aliases]:
                    self._cache[raw_token] = tname
                    return tname
                continue

            # Regex match
            if mode == 'regex':
                if hasattr(trig, '_compiled_regex'):
                    if trig['_compiled_regex'].fullmatch(raw_token):
                        self._cache[raw_token] = tname
                        return tname
                continue

            # Fuzzy match
            for alias in aliases:
                alias_clean = "".join(ch for ch in alias.lower() if ch.isalpha())
                if not alias_clean:
                    continue
                if self.require_first_char and clean[0] != alias_clean[0]:
                    continue
                
                dist = levenshtein_distance(clean, alias_clean)
                if dist < best_distance:
                    best_distance = dist
                    best_trigger = tname

        result = best_trigger if (best_trigger is not None and best_distance <= self.max_distance) else None
        self._cache[raw_token] = result
        return result

    def clear_cache(self):
        """Clear classification cache"""
        self._cache.clear()
