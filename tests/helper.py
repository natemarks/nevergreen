#!/usr/bin/env python3
"""Reusable helpers for unit tests and golden-file workflows.

Purpose:
- Computes per-test case data directories under `test_data/...`.
- Provides small text/JSON read/write helpers used by golden tests.

Customize:
- Keep `case_data_path` naming semantics so existing golden data layout remains
  deterministic.
- Extend with additional serialization helpers only if multiple test modules
  need them.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from config.helper import PROJECT_ROOT


def case_data_path(request: pytest.FixtureRequest) -> Path:
    """Return case-data directory for the current test node.

    Path format:
    - non-parametrized: `test_data/<module>/<function>/`
    - parametrized: `test_data/<module>/<function>/<case_id>/`
    """
    module_dir = request.node.location[0].removesuffix(".py")
    module_data = "test_data" + str(module_dir).removeprefix("tests")
    function_name = request.node.originalname
    try:
        case_name = request.node.callspec.id + "/"
    except AttributeError:
        case_name = ""
    return PROJECT_ROOT / f"{module_data}/{function_name}/{case_name}"


def case_file_path(base_path: Path, relative_path: str) -> Path:
    """Return a file path under a case-data directory."""
    return base_path / relative_path


def write_case_text(
    base_path: Path, relative_path: str, contents: str
) -> None:
    """Write UTF-8 text under case data, creating parent directories."""
    full_path = base_path / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(contents, encoding="utf-8")


def read_case_text(base_path: Path, relative_path: str) -> str:
    """Read UTF-8 text from case data."""
    full_path = case_file_path(base_path, relative_path)
    if not full_path.is_file():
        raise FileNotFoundError(
            f"The file at {full_path} does not exist. "
            "Run 'make unit-update_golden' to generate it."
        )
    return full_path.read_text(encoding="utf-8")


def write_case_json(base_path: Path, relative_path: str, payload: Any) -> None:
    """Write indented JSON under case data."""
    write_case_text(base_path, relative_path, json.dumps(payload, indent=2))


def read_case_json(base_path: Path, relative_path: str) -> Any:
    """Read JSON data from case data."""
    return json.loads(read_case_text(base_path, relative_path))
