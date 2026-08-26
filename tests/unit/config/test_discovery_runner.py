"""Tests for config.discover.DiscoveryRunner."""

# pylint: disable=redefined-outer-name
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.discover import DiscoveryRunner
from config.registry import StackFactory


@pytest.fixture
def patched_runner(tmp_path):
    """Return a DiscoveryRunner with check_aws_account suppressed."""
    with patch("config.discover.check_aws_account"):
        runner = DiscoveryRunner("dev")
    runner.data_path = tmp_path
    return runner


@pytest.mark.unit
def test_run_calls_discover_for_factories_with_discover(
    monkeypatch, patched_runner
):
    """run() invokes discover on each factory that has a non-None discover."""
    mock_a = MagicMock()
    mock_b = MagicMock()
    factories = [
        StackFactory(deploy=MagicMock(), discover=mock_a),
        StackFactory(deploy=MagicMock(), discover=None),
        StackFactory(deploy=MagicMock(), discover=mock_b),
    ]
    monkeypatch.setitem(
        __import__(
            "config.discover", fromlist=["STACKS_BY_ENV"]
        ).STACKS_BY_ENV,
        "dev",
        factories,
    )
    patched_runner.run()

    mock_a.assert_called_once_with(patched_runner.data_path)
    mock_b.assert_called_once_with(patched_runner.data_path)


@pytest.mark.unit
def test_run_skips_factories_with_no_discover(monkeypatch, patched_runner):
    """run() silently skips factories whose discover is None."""
    deploy_mock = MagicMock()
    factories = [
        StackFactory(deploy=deploy_mock, discover=None),
    ]
    monkeypatch.setitem(
        __import__(
            "config.discover", fromlist=["STACKS_BY_ENV"]
        ).STACKS_BY_ENV,
        "dev",
        factories,
    )
    patched_runner.run()
    deploy_mock.assert_not_called()


@pytest.mark.unit
def test_run_passes_data_path_to_discover(
    monkeypatch, patched_runner, tmp_path
):
    """run() passes self.data_path to each factory's discover callable."""
    expected_path = tmp_path / "some_env"
    patched_runner.data_path = expected_path
    captured: list[Path] = []
    factories = [
        StackFactory(
            deploy=MagicMock(),
            discover=captured.append,
        )
    ]
    monkeypatch.setitem(
        __import__(
            "config.discover", fromlist=["STACKS_BY_ENV"]
        ).STACKS_BY_ENV,
        "dev",
        factories,
    )
    patched_runner.run()
    assert captured == [expected_path]
