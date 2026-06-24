"""Pytest configuration and fixtures"""

import sys
from pathlib import Path

# Add parser_lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))
