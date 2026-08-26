"""Unit tests for shared test helper utilities.

Purpose:
- Keep the `test_data/...` path contract stable.
- Keep golden-file read/write helpers stable and predictable.
"""

import pytest

from tests.helper import (
    case_data_path,
    case_file_path,
    read_case_json,
    read_case_text,
    write_case_json,
    write_case_text,
)
from tests.unit.config.settings._shared import expected_module_data_root


@pytest.mark.unit
def test_case_data_path_no_params_uses_function_name(request):
    """Non-parametrized tests resolve to <function_name>/ under test_data."""
    data_path = case_data_path(request)

    assert data_path.parent == expected_module_data_root("test_helper")
    assert data_path.name == "test_case_data_path_no_params_uses_function_name"


@pytest.mark.unit
@pytest.mark.parametrize(
    "stack_id",
    [
        pytest.param("aaa", id="aaa"),
    ],
)
def test_case_data_path_with_params_uses_case_id(request, stack_id):
    """Parametrized tests resolve to <function_name>/<case_id>/ under test_data."""
    data_path = case_data_path(request)

    assert (
        data_path.parent
        == expected_module_data_root("test_helper")
        / "test_case_data_path_with_params_uses_case_id"
    )
    assert data_path.name == stack_id


@pytest.mark.unit
def test_case_file_path_joins_base_and_relative_path(tmp_path):
    """case_file_path appends relative paths correctly."""
    result = case_file_path(tmp_path, "foo/bar.txt")

    assert result == tmp_path / "foo/bar.txt"


@pytest.mark.unit
def test_case_text_round_trip(tmp_path):
    """write_case_text and read_case_text round trip text content."""
    contents = "myoasdjkfasf,xt_contents"

    write_case_text(tmp_path, "expected.txt", contents)
    result = read_case_text(tmp_path, "expected.txt")

    assert result == contents


@pytest.mark.unit
def test_case_json_round_trip(tmp_path):
    """write_case_json and read_case_json round trip JSON data."""
    payload = {
        "number": 1,
        "list": ["a", "b"],
        "nested": {"ok": True},
    }

    write_case_json(tmp_path, "expected.json", payload)
    result = read_case_json(tmp_path, "expected.json")

    assert result == payload


@pytest.mark.unit
def test_read_case_text_raises_for_missing_file(tmp_path):
    """read_case_text fails clearly for missing files."""
    missing_path = tmp_path / "missing.txt"

    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        read_case_text(tmp_path, "missing.txt")
