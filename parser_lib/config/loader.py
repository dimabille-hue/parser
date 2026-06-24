"""Configuration loader"""

import json
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigLoader:
    """Load and validate parser configuration"""

    @staticmethod
    def load_json(path: str) -> Dict[str, Any]:
        """Load configuration from JSON file
        
        Args:
            path: Path to JSON config file
            
        Returns:
            Configuration dict
            
        Raises:
            FileNotFoundError: If file not found
            json.JSONDecodeError: If JSON is invalid
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def validate_basic(config: Dict[str, Any]) -> list:
        """Validate basic config structure
        
        Args:
            config: Configuration dict
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        # Check required fields
        required = ('parser_name', 'csv_columns', 'triggers')
        for key in required:
            if key not in config:
                errors.append(f"Missing required key: '{key}'")
        
        # Check types
        if 'parser_name' in config and not isinstance(config['parser_name'], str):
            errors.append("'parser_name' must be a string")
        
        if 'csv_columns' in config:
            cols = config['csv_columns']
            if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
                errors.append("'csv_columns' must be a list of strings")
        
        if 'triggers' in config:
            triggers = config['triggers']
            if not isinstance(triggers, dict) or len(triggers) == 0:
                errors.append("'triggers' must be a non-empty dict")
        
        return errors
