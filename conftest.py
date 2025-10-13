import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register coverage-related options when pytest-cov is unavailable.

    The Phase 0 bootstrap config expects ``pytest-cov`` to be installed and
    configures ``--cov`` and ``--cov-report`` via ``pytest.ini``. In environments
    without access to PyPI we still want the test suite to run, so we provide a
    lightweight shim that registers the options and ignores them gracefully.
    """

    group = parser.getgroup("coverage")
    group.addoption(
        "--cov",
        action="append",
        dest="cov_targets",
        default=[],
        help="No-op coverage target placeholder when pytest-cov is absent.",
    )
    group.addoption(
        "--cov-report",
        action="append",
        dest="cov_reports",
        default=[],
        help="No-op coverage report placeholder when pytest-cov is absent.",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Emit a gentle notice so it's clear coverage is not being collected."""

    if not config.pluginmanager.hasplugin("cov") and (
        config.getoption("cov_targets") or config.getoption("cov_reports")
    ):
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(
                "pytest-cov is not installed; coverage collection skipped."
            ),
            stacklevel=2,
        )
