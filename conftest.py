from __future__ import annotations

import ast
import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set

import pytest


@dataclass
class _ModuleCoverage:
    """Record basic statement counts when pytest-cov is unavailable."""

    targets: Sequence[str]
    reports: Sequence[str]
    project_root: Path = field(default_factory=lambda: Path.cwd())
    source_map: Dict[str, Set[int]] = field(default_factory=dict)

    def prepare(self) -> bool:
        """Resolve target modules into Python source files."""

        self.source_map = {}
        for candidate in self._iter_target_files():
            statements = self._collect_statement_lines(candidate)
            if statements:
                self.source_map[str(candidate.resolve())] = statements
        return bool(self.source_map)

    def report(self, terminalreporter) -> None:
        if not self.source_map:
            return
        include_term = any(
            report.startswith("term") for report in self.reports or ("term",)
        )
        include_missing = any(
            report.endswith("missing") for report in self.reports or ()
        )
        if not include_term:
            return

        total_files = len(self.source_map)
        total_statements = sum(len(lines) for lines in self.source_map.values())

        terminalreporter.write_sep("-", "coverage summary (simple)")
        terminalreporter.write_line(
            "pytest-cov is not installed; install it to enable accurate coverage reporting."
        )
        terminalreporter.write_line(
            f"Measured modules: {total_files} | Total statements: {total_statements} | Coverage: n/a"
        )
        if include_missing:
            terminalreporter.write_line(
                "Missing line detail is unavailable without pytest-cov."
            )

    def _iter_target_files(self) -> Iterable[Path]:
        for target in self.targets:
            try:
                module = importlib.import_module(target)
            except Exception:
                continue
            origin = getattr(module, "__file__", None)
            if not origin:
                continue
            path = Path(origin).resolve()
            if path.is_dir():
                candidates = path.rglob("*.py")
            elif path.name == "__init__.py":
                candidates = path.parent.rglob("*.py")
            else:
                candidates = (path,)
            for file_path in candidates:
                if not file_path.is_file():
                    continue
                if "tests" in file_path.parts:
                    continue
                yield file_path

    def _collect_statement_lines(self, path: Path) -> Set[int]:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        lines: Set[int] = set()
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            if lineno is None:
                continue
            end_lineno = getattr(node, "end_lineno", lineno)
            lines.update(range(lineno, end_lineno + 1))
        return lines


_SIMPLE_COVERAGE: _ModuleCoverage | None = None


@pytest.hookimpl(tryfirst=True)
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register coverage options when ``pytest-cov`` is not importable."""

    if importlib.util.find_spec("pytest_cov") is not None:
        return

    group = parser.getgroup("coverage")
    group.addoption(
        "--cov",
        action="append",
        dest="cov_targets",
        default=[],
        help="Measure coverage for the specified package or module.",
    )
    group.addoption(
        "--cov-report",
        action="append",
        dest="cov_reports",
        default=[],
        help="Generate a simple coverage report placeholder (supports term, term-missing).",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Activate the lightweight coverage shim when pytest-cov is absent."""

    if config.pluginmanager.hasplugin("cov"):
        return

    targets: List[str] = config.getoption("cov_targets")
    reports: List[str] = config.getoption("cov_reports")
    if not targets and not reports:
        return

    coverage = _ModuleCoverage(targets=targets, reports=reports)
    if not coverage.prepare():
        config._cov_plugin_missing = True  # type: ignore[attr-defined]
        return

    global _SIMPLE_COVERAGE
    _SIMPLE_COVERAGE = coverage
    config._simple_coverage = coverage  # type: ignore[attr-defined]


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if _SIMPLE_COVERAGE is not None:
        _SIMPLE_COVERAGE.report(terminalreporter)
    elif getattr(config, "_cov_plugin_missing", False):
        terminalreporter.write_sep(
            "-",
            "pytest-cov plugin unavailable; skipping configured coverage collection",
        )
