"""Shared filesystem path constants for the SimpleSpecs backend."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_UPLOAD_DIR = ROOT / "uploads"
DEFAULT_EXPORT_DIR = ROOT / "exports"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", DEFAULT_UPLOAD_DIR))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", DEFAULT_EXPORT_DIR))

__all__ = [
    "ROOT",
    "FRONTEND_DIR",
    "DEFAULT_UPLOAD_DIR",
    "DEFAULT_EXPORT_DIR",
    "UPLOAD_DIR",
    "EXPORT_DIR",
]
