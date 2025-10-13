"""Proxy module that patches upstream PyMuPDF import-time warnings."""
from __future__ import annotations

import gc
import importlib
import importlib.machinery
import importlib.util
import sys
import warnings
from pathlib import Path
from types import ModuleType


def _load_upstream_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parent.parent
    search_paths = [
        entry
        for entry in sys.path
        if Path(entry).resolve() != repo_root
    ]
    spec = importlib.machinery.PathFinder.find_spec("pymupdf", search_paths)
    if spec is None or spec.origin == __file__:
        raise ImportError("Unable to locate upstream pymupdf distribution")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    previous = sys.modules.get("pymupdf")
    sys.modules["pymupdf"] = module
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="builtin type .* has no __module__ attribute",
                category=DeprecationWarning,
            )
            spec.loader.exec_module(module)
    except Exception:
        if previous is not None:
            sys.modules["pymupdf"] = previous
        else:
            sys.modules.pop("pymupdf", None)
        raise
    return module


def _patch_swigtpes() -> None:
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="builtin type .* has no __module__ attribute",
                category=DeprecationWarning,
            )
            importlib.import_module(".mupdf", __name__)
    except Exception:
        return

    pending = {"SwigPyPacked", "SwigPyObject", "swigvarlink"}
    try:
        for candidate in gc.get_objects():
            if not isinstance(candidate, type):
                continue
            name = getattr(candidate, "__name__", None)
            if name not in pending:
                continue
            if getattr(candidate, "__module__", None) != "pymupdf.mupdf":
                try:
                    candidate.__module__ = "pymupdf.mupdf"
                except Exception:
                    continue
            pending.discard(name)
            if not pending:
                break
    except Exception:
        return


_upstream = _load_upstream_module()
sys.modules[__name__] = _upstream
_patch_swigtpes()
globals().update(_upstream.__dict__)
