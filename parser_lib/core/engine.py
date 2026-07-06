"""Main parsing engine - orchestrates all components"""

from typing import Dict, List, Optional, Tuple, Set
from collections import Counter
import logging

from parser_lib.core.tokenizer import TokenizerFactory
from parser_lib.core.classifier import Classifier
from parser_lib.core.normalizer import NormalizerFactory
from parser_lib.core.validator import ValidatorFactory
from parser_lib.config.loader import ConfigLoader


class ParseEngine:
    """Main parsing engine that orchestrates all components
    
    This class brings together:
    - Tokenization
    - Classification (trigger matching)
    - Field collection
    - Normalization
    - Validation
    - Duplicate detection
    - Statistics computation
    
    Example:
        ```python
        from parser_lib import ParseEngine
        from parser_lib.config.loader import ConfigLoader
        
        config = ConfigLoader.load_json('config.json')
        engine = ParseEngine(config)
        
        results = engine.parse(text)
        # results = [{'яч': '1', 'ном': '418/4', 'фио/орг': 'Смирнов', 'err': ''},
        #            {'яч': '2', 'ном': '6/8', 'фио/орг': 'Петров', 'err': 'errDUP'}]
        
        stats = engine.get_stats()
        # stats = {'total': 2, 'clean': 1, 'with_errors': 1, 'error_rate': 50.0, ...}
        ```
    """

    def __init__(self, config: Dict, debug: bool = False):
        """Initialize ParseEngine with configuration
        
        Args:
            config: Configuration dictionary (from ConfigLoader.load_json)
            debug: Enable debug logging
            
        Raises:
            ValueError: If config validation fails
        """
        # Validate config
        errors = ConfigLoader.validate_basic(config)
        if errors:
            raise ValueError(f"Invalid config: {errors}")
        
        self.config = config
        self.debug = debug
        self.logger = logging.getLogger('parser_lib')
        
        # Initialize components
        self.tokenizer = TokenizerFactory.create(
            config.get('tokenizer', {}).get('split_by', 'whitespace')
        )
        self.classifier = Classifier(
            config['triggers'],
            max_distance=config.get('max_distance', 1),
            require_first_char=config.get('require_first_char', True),
            stop_words=set(config.get('stop_words', [])),
            debug=debug
        )
        
        # Build normalizers and validators for each trigger
        self.normalizers: Dict[str, callable] = {}
        self.validators: Dict[str, callable] = {}
        self._build_normalizers_and_validators()
        
        # State
        self.records: List[Dict] = []
        self.suspicious_log: Counter = Counter()
        self.debug_log: List[str] = []
        self.stats: Dict = {}

    def _build_normalizers_and_validators(self):
        """Build normalizer and validator functions for each trigger"""
        for trigger_name, trigger_config in self.config['triggers'].items():
            # Build normalizer
            if 'normalization' in trigger_config:
                pipeline_steps = trigger_config['normalization'].get('pipeline', [])
                replacements = trigger_config.get('replacements')
                self.normalizers[trigger_name] = NormalizerFactory.create_pipeline(
                    pipeline_steps,
                    replacements
                ).normalize
            else:
                self.normalizers[trigger_name] = lambda x: x.strip()
            
            # Build validator
            if 'validation' in trigger_config:
                rule = trigger_config['validation'].get('rule', 'not_empty')
                self.validators[trigger_name] = ValidatorFactory.create(rule)
            else:
                self.validators[trigger_name] = None

    def parse(self, text: str) -> List[Dict[str, str]]:
        """Parse text and extract records
        
        Args:
            text: Input text to parse
            
        Returns:
            List of parsed records with fields and errors
            
        Example:
            ```python
            results = engine.parse("Яч 1. Ном. 418.4. Фио. Смирнов.")
            # [{'яч': '1', 'ном': '418/4', 'фио/орг': 'Смирнов', 'err': ''}]
            ```
        """
        self.records = []
        self.suspicious_log = Counter()
        self.debug_log = []
        
        # Clean and tokenize
        tokens = self.tokenizer.tokenize(text)
        if self.debug:
            self.logger.debug(f"Tokenized {len(tokens)} tokens")
        
        # Segment into records
        segments = self._segment_tokens(tokens)
        if self.debug:
            self.logger.debug(f"Segmented into {len(segments)} records")
        
        # Parse each segment
        for segment_tokens in segments:
            record = self._parse_record(segment_tokens)
            self.records.append(record)
        
        # Detect duplicates
        if 'dedup' in self.config:
            self._detect_duplicates()
        
        # Compute statistics
        self.stats = self._compute_stats()
        
        return self.records

    def _segment_tokens(self, tokens: List[str]) -> List[List[str]]:
        """Segment tokens into records based on record_detection config
        
        Args:
            tokens: List of tokens
            
        Returns:
            List of token segments (one per record)
        """
        record_detection = self.config.get('record_detection')
        
        if not record_detection:
            return [tokens]
        
        mode = record_detection.get('mode', 'trigger')
        if mode != 'trigger':
            return [tokens]
        
        trigger_name = record_detection.get('trigger')
        if not trigger_name:
            return [tokens]
        
        # Segment by trigger
        segments = []
        current_segment = []
        
        for token in tokens:
            trigger = self.classifier.classify(token)
            
            # Check if this is the record-starting trigger
            if trigger == trigger_name and current_segment:
                segments.append(current_segment)
                current_segment = []
            
            current_segment.append(token)
        
        if current_segment:
            segments.append(current_segment)
        
        # Apply continuation heuristics if configured
        if 'continuation_heuristics' in record_detection:
            segments = self._apply_continuation_heuristics(segments, record_detection)
        
        return segments

    def _apply_continuation_heuristics(self, segments: List[List[str]], 
                                      record_detection: Dict) -> List[List[str]]:
        """Merge segments based on continuation heuristics
        
        Args:
            segments: List of token segments
            record_detection: Record detection configuration
            
        Returns:
            Merged segments
        """
        if len(segments) <= 1:
            return segments
        
        heuristics = record_detection.get('continuation_heuristics', {})
        detect_by_expr = heuristics.get('detect_by', 'any')
        max_tokens_to_check = heuristics.get('max_tokens_to_check', 5)
        
        from parser_lib.core.predicates import PredicateFactory
        predicate = PredicateFactory.create(detect_by_expr)
        
        trigger_name = record_detection.get('trigger')
        merged_segments = []
        i = 0
        
        while i < len(segments):
            current = segments[i]
            merged_segments.append(current)
            i += 1
            
            # Try to merge following segments
            merge_count = 0
            merge_limit = len(segments) - 1
            
            while i < len(segments) and merge_count < merge_limit:
                next_segment = segments[i]
                
                # Don't merge if next starts with trigger
                if next_segment and self.classifier.classify(next_segment[0]) == trigger_name:
                    break
                
                # Check if first tokens match predicate
                tokens_to_check = next_segment[:max_tokens_to_check]
                if any(predicate(token) for token in tokens_to_check):
                    # Merge
                    merged_segments[-1].extend(next_segment)
                    i += 1
                    merge_count += 1
                else:
                    break
        
        return merged_segments

    def _parse_record(self, tokens: List[str]) -> Dict[str, str]:
        """Parse a single record from tokens
        
        Args:
            tokens: Tokens for this record
            
        Returns:
            Dictionary with field names and values
        """
        record = {}
        errors = set()
        
        current_field = None
        value_buffer = []
        
        for token in tokens:
            # Try to classify token as trigger
            trigger = self.classifier.classify(token)
            
            if trigger:
                # Save previous field
                if current_field:
                    self._save_field(record, current_field, value_buffer, errors)
                    value_buffer = []
                
                # Open new field
                current_field = trigger
                trigger_config = self.config['triggers'][trigger]
                
                # Activate collector if configured
                if trigger_config.get('on_new_record'):
                    # Mark new record (handled by segmentation)
                    pass
            else:
                # Add to current field or lose it
                if current_field:
                    value_buffer.append(token)
                else:
                    if self.config.get('log_suspicious', False):
                        self.suspicious_log[token] += 1
        
        # Save last field
        if current_field:
            self._save_field(record, current_field, value_buffer, errors)
        
        # Add errors
        if errors:
            record['err'] = ' '.join(sorted(errors))
        else:
            record['err'] = ''
        
        return record

    def _save_field(self, record: Dict, field_name: str, tokens: List[str], 
                   errors: Set[str]):
        """Save field value after normalization and validation
        
        Args:
            record: Record dictionary to update
            field_name: Trigger/field name
            tokens: Collected tokens for this field
            errors: Set to accumulate error codes
        """
        if not tokens:
            return
        
        # Join tokens
        raw_value = ' '.join(tokens)
        
        # Normalize
        normalizer = self.normalizers.get(field_name)
        if normalizer:
            value = normalizer(raw_value)
        else:
            value = raw_value.strip()
        
        if not value:
            return
        
        # Validate
        validator = self.validators.get(field_name)
        if validator and not validator.validate(value):
            error_code = self.config['triggers'][field_name].get(
                'validation', {}
            ).get('error_code', 'errVAL')
            errors.add(error_code)
        
        # Save to record
        csv_column = self.config['triggers'][field_name].get(
            'csv_column', field_name
        )
        record[csv_column] = value

    def _detect_duplicates(self):
        """Mark duplicate records based on dedup configuration"""
        dedup_config = self.config.get('dedup', {})
        if not dedup_config:
            return
        
        key_field = dedup_config.get('key')
        error_code = dedup_config.get('error_code', 'errDUP')
        case_sensitive = dedup_config.get('case_sensitive', False)
        
        if not key_field:
            return
        
        seen = set()
        duplicates_found = 0
        
        for record in self.records:
            value = record.get(key_field, '')
            if not value:
                continue
            
            check_value = value if case_sensitive else value.lower()
            
            if check_value in seen:
                # Mark as duplicate
                if record.get('err'):
                    record['err'] += f" {error_code}"
                else:
                    record['err'] = error_code
                duplicates_found += 1
            else:
                seen.add(check_value)
        
        self.stats['duplicates'] = duplicates_found
        if self.debug:
            self.logger.debug(f"Found {duplicates_found} duplicates")

    def _compute_stats(self) -> Dict:
        """Compute statistics for parsed records
        
        Returns:
            Statistics dictionary
        """
        stats = {
            'total': len(self.records),
            'clean': 0,
            'with_errors': 0,
            'error_rate': 0.0,
            'top_errors': [],
            'field_fill': {},
            'duplicates': 0,
            'value_distribution': {}
        }
        
        if not self.records:
            return stats
        
        error_counter = Counter()
        field_counters = {col: 0 for col in self.config['csv_columns']}
        field_values = {col: Counter() for col in self.config['csv_columns']}
        
        for record in self.records:
            # Count errors
            if record.get('err'):
                stats['with_errors'] += 1
                error_counter.update(record['err'].split())
            else:
                stats['clean'] += 1
            
            # Count field fills and values
            for col in self.config['csv_columns']:
                value = record.get(col, '')
                if value:
                    field_counters[col] += 1
                    field_values[col][value] += 1
        
        # Calculate error rate
        if stats['total'] > 0:
            stats['error_rate'] = (stats['with_errors'] / stats['total']) * 100
        
        # Top errors
        stats['top_errors'] = error_counter.most_common(10)
        
        # Field fill
        stats['field_fill'] = field_counters
        
        # Value distribution
        for col in self.config['csv_columns']:
            unique_values = len(field_values[col])
            filled = field_counters[col]
            repeated = [
                (val, count) for val, count in field_values[col].most_common(8)
                if count > 1
            ]
            
            stats['value_distribution'][col] = {
                'unique': unique_values,
                'filled': filled,
                'repeated': repeated,
                'repeated_total': len(repeated)
            }
        
        return stats

    def get_stats(self) -> Dict:
        """Get statistics for last parse operation
        
        Returns:
            Statistics dictionary
        """
        return self.stats

    def get_records(self) -> List[Dict[str, str]]:
        """Get parsed records from last parse operation
        
        Returns:
            List of records
        """
        return self.records

    def get_suspicious_tokens(self, limit: int = 50) -> List[Tuple[str, int]]:
        """Get tokens that didn't match any field
        
        Args:
            limit: Maximum number of tokens to return
            
        Returns:
            List of (token, count) tuples
        """
        return self.suspicious_log.most_common(limit)

    def get_debug_log(self) -> List[str]:
        """Get debug log from last parse operation
        
        Returns:
            List of debug messages
        """
        return self.debug_log
