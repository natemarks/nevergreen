"""Tests for config.model_sync."""

# pylint: disable=redefined-outer-name
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.model_sync import (
    _read_dotenv_value,
    load_manifest,
    local_ollama_models_dir,
    sync_checkpoints,
    sync_ollama_models,
)
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
def test_load_manifest_returns_the_configured_sections(tmp_path):
    """load_manifest parses the JSON manifest's checkpoints/ollama_models."""
    manifest_path = tmp_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoints": [
                    {"repo_id": "org/model", "filename": "model.safetensors"}
                ],
                "ollama_models": ["llama3.1"],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path)

    assert manifest["checkpoints"] == [
        {"repo_id": "org/model", "filename": "model.safetensors"}
    ]
    assert manifest["ollama_models"] == ["llama3.1"]


@pytest.mark.unit
def test_sync_checkpoints_downloads_and_uploads_every_manifest_entry(
    data_path,
):
    """sync_checkpoints downloads each entry from HF and uploads it."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoints": [
                    {"repo_id": "org/one", "filename": "one.safetensors"},
                    {"repo_id": "org/two", "filename": "two.safetensors"},
                ]
            }
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
        keys = sync_checkpoints(
            "dev", manifest_path=manifest_path, s3_client=s3
        )

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
def test_sync_checkpoints_passes_the_dotenv_hf_token_to_each_download(
    data_path,
):
    """A HF_TOKEN found in .env is forwarded to every hf_hub_download call."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoints": [
                    {"repo_id": "org/one", "filename": "one.safetensors"}
                ]
            }
        ),
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
        sync_checkpoints("dev", manifest_path=manifest_path, s3_client=s3)

    mock_download.assert_called_once_with(
        repo_id="org/one", filename="one.safetensors", token="hf_abc123"
    )


@pytest.mark.unit
def test_sync_checkpoints_defaults_to_empty_when_section_absent(data_path):
    """A manifest with no "checkpoints" key syncs nothing, not an error."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps({"ollama_models": ["llama3.1"]}), encoding="utf-8"
    )

    with patch("config.model_sync.check_aws_account"), patch(
        "config.model_sync.get_actual_path", return_value=data_path
    ):
        keys = sync_checkpoints(
            "dev", manifest_path=manifest_path, s3_client=MagicMock()
        )

    assert keys == []


@pytest.mark.unit
def test_local_ollama_models_dir_respects_env_override(monkeypatch):
    """OLLAMA_MODELS, when set, overrides the default ~/.ollama/models path."""
    monkeypatch.setenv("OLLAMA_MODELS", "/custom/ollama/models")
    assert str(local_ollama_models_dir()) == "/custom/ollama/models"


@pytest.mark.unit
def test_local_ollama_models_dir_defaults_to_home(monkeypatch):
    """With no override, the default is ~/.ollama/models."""
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    assert local_ollama_models_dir() == Path.home() / ".ollama" / "models"


@pytest.mark.unit
def test_sync_ollama_models_pulls_each_model_then_syncs_to_s3(data_path):
    """Each manifest model is pulled locally, then the whole dir is synced."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(
        json.dumps({"ollama_models": ["llama3.1", "mistral"]}),
        encoding="utf-8",
    )
    runner = MagicMock()

    with patch("config.model_sync.check_aws_account"), patch(
        "config.model_sync.get_actual_path", return_value=data_path
    ):
        model_names = sync_ollama_models(
            "dev",
            manifest_path=manifest_path,
            models_dir="/home/op/.ollama/models",
            runner=runner,
        )

    assert model_names == ["llama3.1", "mistral"]
    runner.assert_any_call(["ollama", "pull", "llama3.1"], check=True)
    runner.assert_any_call(["ollama", "pull", "mistral"], check=True)
    runner.assert_any_call(
        [
            "aws",
            "s3",
            "sync",
            "/home/op/.ollama/models",
            "s3://nevergreen-dev-models/ollama/",
        ],
        check=True,
    )


@pytest.mark.unit
def test_sync_ollama_models_defaults_to_empty_when_section_absent(data_path):
    """A manifest with no "ollama_models" key pulls/syncs nothing."""
    manifest_path = data_path / "model_manifest.json"
    manifest_path.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")
    runner = MagicMock()

    with patch("config.model_sync.check_aws_account"), patch(
        "config.model_sync.get_actual_path", return_value=data_path
    ):
        model_names = sync_ollama_models(
            "dev",
            manifest_path=manifest_path,
            models_dir="/home/op/.ollama/models",
            runner=runner,
        )

    assert model_names == []
    runner.assert_called_once_with(
        [
            "aws",
            "s3",
            "sync",
            "/home/op/.ollama/models",
            "s3://nevergreen-dev-models/ollama/",
        ],
        check=True,
    )
