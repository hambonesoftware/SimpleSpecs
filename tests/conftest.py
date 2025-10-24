"""Test configuration for SimpleSpecs."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root is available on sys.path so tests can import project packages
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
