"""Compatibility layer that re-exports python_multipart without warnings."""

from __future__ import annotations

from python_multipart import *  # noqa: F401,F403
from python_multipart import (
    __all__ as _original_all,
    __author__ as _author,
    __copyright__ as _copyright,
    __license__ as _license,
    __version__ as _version,
)

__all__ = list(_original_all)
__all__.extend(["__author__", "__copyright__", "__license__", "__version__"])

__author__ = _author
__copyright__ = _copyright
__license__ = _license
__version__ = _version
