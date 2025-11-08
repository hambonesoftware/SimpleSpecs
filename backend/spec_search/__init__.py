"""Spec search package wiring for SimpleSpecs."""

from .extractor import extract_buckets
from .reporting import SpecSearchReporter

__all__ = ["extract_buckets", "SpecSearchReporter"]
