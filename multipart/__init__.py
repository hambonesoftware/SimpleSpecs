"""Compatibility layer that re-exports python_multipart without warnings."""
from __future__ import annotations

from python_multipart import *  # noqa: F401,F403
from python_multipart import __all__, __author__, __copyright__, __license__, __version__

__all__ = list(__all__)
