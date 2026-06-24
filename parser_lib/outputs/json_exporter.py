"""JSON exporter"""

import json
from typing import List, Dict


class JSONExporter:
    """Export parsing results to JSON"""

    @staticmethod
    def export(records: List[Dict[str, str]], columns: List[str]) -> bytes:
        """Export records to JSON bytes
        
        Args:
            records: List of record dicts
            columns: Column names
            
        Returns:
            JSON data as bytes (UTF-8)
        """
        cols = columns + (['err'] if 'err' not in columns else [])
        out = [{c: r.get(c, '') for c in cols} for r in records]
        return json.dumps(out, ensure_ascii=False, indent=2).encode('utf-8')

    @staticmethod
    def export_to_file(records: List[Dict[str, str]], columns: List[str], filepath: str):
        """Export records to JSON file
        
        Args:
            records: List of record dicts
            columns: Column names
            filepath: Output file path
        """
        data = JSONExporter.export(records, columns)
        with open(filepath, 'wb') as f:
            f.write(data)
