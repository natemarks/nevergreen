"""Pytest plugin hooks and shared fixtures for this repository.

Purpose:
- Register CLI options used across test modules.
- Expose lightweight fixtures that map to CLI flags.
"""

import pytest


def pytest_addoption(parser):
    """Register `--update_golden` flag for golden-file test updates."""
    parser.addoption(
        "--update_golden", action="store_true", help="update the golden files"
    )


@pytest.fixture
def update_golden(request):
    """Return `True` when pytest runs with `--update_golden`."""
    return request.config.getoption("--update_golden")
