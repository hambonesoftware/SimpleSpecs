"""Compat shim exposing the headers API router and patch points for tests."""

from ..api import headers as headers_api

router = headers_api.router
parse_pdf = headers_api.parse_pdf
extract_headers_and_chunks = headers_api.extract_headers_and_chunks
HeadersLLMClient = headers_api.HeadersLLMClient

__all__ = [
    "router",
    "parse_pdf",
    "extract_headers_and_chunks",
    "HeadersLLMClient",
]
