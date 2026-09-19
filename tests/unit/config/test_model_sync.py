"""Tests for config.model_sync."""

# pylint: disable=redefined-outer-name
import json
from unittest.mock import MagicMock, patch

import pytest

from config.model_sync import _read_dotenv_value, load_manifest, sync_all
from tests.unit.config._shared import (
    write_environment_json as _write_environment_json,
    write_simple_s3_config as _write_simple_s3_config,
)


@pytest.fixture
def data_path(tmp_path):
    """Return a tmp data path with environment.json and a models bucket."""
    _write_environment_json(tmp_path)
    _write_simple_s3_config(tmp_path, "models")
    return tmp_path


@pytest.mark.unit
def test_read_dotenv_value_returns_none_when_file_missing(tmp_path):
    """A missing .env file means no value is found."""
    assert _read_dotenv_value("HF_TOKEN", tmp_path / ".env") is None


@pytest.mark.unit
def test_read_dotenv_value_parses_key_value_pairs(tmp_path):
    """A matching KEY=VALUE line is returned, quotes and whitespace stripped."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        '# a comment\nOTHER=1\nHF_TOKEN="hf_abc123"\n', encoding="utf-8"
    )

    assert _read_dotenv_value("HF_TOKEN", dotenv_path) == "hf_abc123"


@pytest.mark.unit
def test_read_dotenv_value_returns_none_when_key_absent(tmp_path):
    """A .env file that exists but lacks the key returns None."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("OTHER=1\n", encoding="utf-8")

    assert _read_dotenv_value("HF_TOKEN", dotenv_path) is None


@pytest.mark.unit
def test_load_manifest_returns_the_configured_entries(tmp_path):
    """load_manifest parses the JSON manifest into a list of dicts."""
    manifest_path = tmp_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(
            [{"repo_id": "org/model", "filename": "model.safetensors"}]
        ),
        encoding="utf-8",
    )

    assert load_manifest(manifest_path) == [
        {"repo_id": "org/model", "filename": "model.safetensors"}
    ]


@pytest.mark.unit
def test_sync_all_downloads_and_uploads_every_manifest_entry(data_path):
    """sync_all downloads each entry from HF and uploads it to the bucket."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {"repo_id": "org/one", "filename": "one.safetensors"},
                {"repo_id": "org/two", "filename": "two.safetensors"},
            ]
        ),
        encoding="utf-8",
    )
    s3 = MagicMock()

    with patch("config.model_sync.check_aws_account"), patch(
        "config.model_sync.get_actual_path", return_value=data_path
    ), patch(
        "config.model_sync.hf_hub_download",
        side_effect=lambda repo_id, filename, token: f"/cache/{filename}",
    ) as mock_download, patch(
        "config.model_sync._read_dotenv_value", return_value=None
    ):
        keys = sync_all("dev", manifest_path=manifest_path, s3_client=s3)

    assert keys == [
        "checkpoints/one.safetensors",
        "checkpoints/two.safetensors",
    ]
    assert mock_download.call_count == 2
    assert s3.upload_file.call_count == 2
    s3.upload_file.assert_any_call(
        "/cache/one.safetensors",
        "nevergreen-dev-models",
        "checkpoints/one.safetensors",
    )


@pytest.mark.unit
def test_sync_all_passes_the_dotenv_hf_token_to_each_download(data_path):
    """A HF_TOKEN found in .env is forwarded to every hf_hub_download call."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps([{"repo_id": "org/one", "filename": "one.safetensors"}]),
        encoding="utf-8",
    )
    s3 = MagicMock()

    with patch("config.model_sync.check_aws_account"), patch(
        "config.model_sync.get_actual_path", return_value=data_path
    ), patch(
        "config.model_sync.hf_hub_download",
        return_value="/cache/one.safetensors",
    ) as mock_download, patch(
        "config.model_sync._read_dotenv_value", return_value="hf_abc123"
    ):
        sync_all("dev", manifest_path=manifest_path, s3_client=s3)

    mock_download.assert_called_once_with(
        repo_id="org/one", filename="one.safetensors", token="hf_abc123"
    )
