"""TriggerParse — Universal Configurable Parser Library

Version 4.0 - Modular Architecture
"""

__version__ = "4.0.0"
__author__ = "TriggerParse Team"

from parser_lib.core.engine import ParseEngine
from parser_lib.config.loader import ConfigLoader
from parser_lib.outputs.csv_exporter import CSVExporter

__all__ = [
    "ParseEngine",
    "ConfigLoader",
    "CSVExporter",
]
