"""CSV exporter"""

import csv
import io
from typing import List, Dict, Optional


class CSVExporter:
    """Export parsing results to CSV"""

    CSV_FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')

    @staticmethod
    def _escape_formula(value: str) -> str:
        """Escape CSV formula injection
        
        Args:
            value: Cell value
            
        Returns:
            Escaped value
        """
        if value and value[0] in CSVExporter.CSV_FORMULA_CHARS:
            return "'" + value
        return value

    @staticmethod
    def export(
        records: List[Dict[str, str]],
        columns: List[str],
        include_error_column: bool = True
    ) -> bytes:
        """Export records to CSV bytes
        
        Args:
            records: List of record dicts
            columns: Column names
            include_error_column: Add 'err' column if present in records
            
        Returns:
            CSV data as bytes (UTF-8 with BOM)
        """
        cols = columns.copy()
        if include_error_column and 'err' not in cols:
            cols.append('err')
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        
        for rec in records:
            safe_rec = {
                k: CSVExporter._escape_formula(str(v)) if isinstance(v, str) else v
                for k, v in rec.items()
            }
            writer.writerow(safe_rec)
        
        return output.getvalue().encode('utf-8-sig')

    @staticmethod
    def export_to_file(records: List[Dict[str, str]], columns: List[str], filepath: str):
        """Export records to CSV file
        
        Args:
            records: List of record dicts
            columns: Column names
            filepath: Output file path
        """
        data = CSVExporter.export(records, columns)
        with open(filepath, 'wb') as f:
            f.write(data)
