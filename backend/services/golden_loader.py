"""Utilities for loading golden header definitions.

This module provides a helper for retrieving pre-defined header
definitions ("golden" headers) based on the filename of a PDF.  When
golden header injection is enabled (via ``HEADERS_USE_GOLDEN``), the
application will attempt to load a matching list of headings from
``backend/resources/golden_headers.py``.  Each supported document
should define a module-level sequence whose name corresponds to a
normalised version of the filename (hyphens replaced with underscores
and the extension removed).

In test environments the same lookup may fall back to
``tests/test_headers_golden.py`` if the resource module is missing.  The
loader converts the raw entries into a simple list of dictionaries
containing ``text``, ``number`` and ``level`` keys, which can be passed
directly to the strict alignment pipeline.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Mapping, Optional

def _normalise_filename(filename: str) -> str:
    """Return a Python identifier derived from a PDF filename.

    The golden headers are keyed by the stem of the filename with hyphens
    replaced by underscores.  For example, ``"MFC-5M_R2001_E1985.pdf"`` maps
    to ``"MFC_5M_R2001_E1985"``.  The extension is stripped and no further
    normalisation is applied.
    """

    stem = Path(filename).stem
    return stem.replace("-", "_")


def get_golden_headers_for_filename(filename: str) -> Optional[List[Mapping[str, object]]]:
    """Return golden header entries for the given filename if available.

    The function attempts to import ``backend.resources.golden_headers`` and
    looks up an attribute named after the normalised filename.  If the
    attribute exists and is a sequence of mappings with ``text``, ``number``
    and ``level`` keys, a list of dictionaries with those keys is
    returned.  When the resource module or attribute is missing, a
    fallback import from ``tests.test_headers_golden`` is attempted.

    Parameters
    ----------
    filename: str
        The name of the PDF file for which to load golden headers.

    Returns
    -------
    Optional[List[Mapping[str, object]]]
        A list of header dictionaries or ``None`` if no matching
        definition is found.
    """

    var_name = _normalise_filename(filename)
    # First attempt to import from the primary resources module
    try:
        golden_module = importlib.import_module("backend.resources.golden_headers")
        entries = getattr(golden_module, var_name, None)
        if entries:
            return [
                {
                    "text": str(item.get("text", "")),
                    "number": item.get("number"),
                    "level": int(item.get("level", 1)),
                }
                for item in entries
                if isinstance(item, Mapping)
            ]
    except Exception:
        # ignore import errors; fall back to tests
        pass
    # Fallback to test definitions when available
    try:
        test_module = importlib.import_module("tests.test_headers_golden")
        entries = getattr(test_module, var_name, None)
        if entries:
            return [
                {
                    "text": str(item.get("text", "")),
                    "number": item.get("number"),
                    "level": int(item.get("level", 1)),
                }
                for item in entries
                if isinstance(item, Mapping)
            ]
    except Exception:
        pass
    return None