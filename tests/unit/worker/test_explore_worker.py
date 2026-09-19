#!/usr/bin/env python3
"""Unit tests for the explore-a worker's pure functions.

Purpose:
- Cover the seams that don't need real AWS/HTTP: config parsing, workflow
  graph mutation, and the S3-upload/queue-poll loop with mocked clients.

Customize:
- Add cases here whenever explore_worker.py's pure functions change shape.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from worker.explore_worker import (
    WorkerConfig,
    build_workflow,
    find_node_id,
    poll_queue,
    process_job,
    upload_images_to_s3,
)


@pytest.mark.unit
def test_worker_config_from_env_requires_only_queue_and_bucket():
    """Defaults fill in every field except the two required ones."""
    config = WorkerConfig.from_env(
        {"QUEUE_URL": "queue-url", "OUTPUT_BUCKET": "bucket"}
    )
    assert config.queue_url == "queue-url"
    assert config.output_bucket == "bucket"
    assert config.comfyui_url == "http://localhost:8188"
    assert config.ollama_url == "http://localhost:11434"
    assert config.comfyui_output_dir == Path("/opt/comfyui/output")


@pytest.mark.unit
def test_worker_config_from_env_overrides_defaults():
    """Every optional env var overrides its corresponding default."""
    config = WorkerConfig.from_env(
        {
            "QUEUE_URL": "queue-url",
            "OUTPUT_BUCKET": "bucket",
            "COMFYUI_URL": "http://comfy:1234",
            "OLLAMA_URL": "http://ollama:5678",
            "OLLAMA_MODEL": "mistral",
            "COMFYUI_OUTPUT_DIR": "/tmp/out",
            "WORKFLOW_TEMPLATE_PATH": "/tmp/workflow.json",
            "AWS_REGION": "us-west-2",
        }
    )
    assert config.comfyui_url == "http://comfy:1234"
    assert config.ollama_url == "http://ollama:5678"
    assert config.ollama_model == "mistral"
    assert config.comfyui_output_dir == Path("/tmp/out")
    assert config.workflow_template_path == Path("/tmp/workflow.json")
    assert config.aws_region == "us-west-2"


@pytest.mark.unit
def test_find_node_id_returns_matching_node():
    """The node id whose class_type matches is returned."""
    workflow = {
        "1": {"class_type": "CLIPTextEncode"},
        "2": {"class_type": "SaveImage"},
    }
    assert find_node_id(workflow, "SaveImage") == "2"


@pytest.mark.unit
def test_find_node_id_raises_when_missing():
    """A class_type with no matching node raises ValueError."""
    with pytest.raises(ValueError, match="KSampler"):
        find_node_id({"1": {"class_type": "SaveImage"}}, "KSampler")


def _sample_template() -> dict:
    return {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "2": {
            "class_type": "KSampler",
            "inputs": {"positive": ["1", 0], "seed": 0},
        },
        "3": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "old"},
        },
    }


@pytest.mark.unit
def test_build_workflow_sets_prompt_seed_and_prefix():
    """The KSampler's positive-link node gets the new prompt text."""
    result = build_workflow(_sample_template(), "a cat", 42, "job_0")
    assert result["1"]["inputs"]["text"] == "a cat"
    assert result["2"]["inputs"]["seed"] == 42
    assert result["3"]["inputs"]["filename_prefix"] == "job_0"


@pytest.mark.unit
def test_build_workflow_does_not_mutate_template():
    """The input template is left untouched -- callers reuse it per prompt."""
    template = _sample_template()
    build_workflow(template, "a cat", 42, "job_0")
    assert template["1"]["inputs"]["text"] == "old"
    assert template["2"]["inputs"]["seed"] == 0
    assert template["3"]["inputs"]["filename_prefix"] == "old"


@pytest.mark.unit
def test_upload_images_to_s3_uploads_each_image_and_returns_keys():
    """Each image is uploaded under explore/{job_id}/{filename}."""
    s3_client = MagicMock()
    images = [
        {"filename": "a.png", "subfolder": ""},
        {"filename": "b.png", "subfolder": "sub"},
    ]
    keys = upload_images_to_s3(
        images, Path("/out"), "my-bucket", "job-1", s3_client
    )
    assert keys == ["explore/job-1/a.png", "explore/job-1/b.png"]
    assert s3_client.upload_file.call_count == 2
    s3_client.upload_file.assert_any_call(
        str(Path("/out/a.png")), "my-bucket", "explore/job-1/a.png"
    )
    s3_client.upload_file.assert_any_call(
        str(Path("/out/sub/b.png")), "my-bucket", "explore/job-1/b.png"
    )


@pytest.mark.unit
def test_process_job_expands_generates_and_uploads_each_prompt(tmp_path):
    """process_job wires expand -> build -> submit -> wait -> upload."""
    template_path = tmp_path / "workflow.json"
    template_path.write_text(
        '{"1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}, '
        '"2": {"class_type": "KSampler", '
        '"inputs": {"positive": ["1", 0], "seed": 0}}, '
        '"3": {"class_type": "SaveImage", '
        '"inputs": {"filename_prefix": ""}}}',
        encoding="utf-8",
    )
    config = WorkerConfig(
        queue_url="q",
        output_bucket="bucket",
        workflow_template_path=template_path,
    )
    job = {"job_id": "job-1", "seed_prompt": "a cat", "batch_size": 2}
    s3_client = MagicMock()

    with patch(
        "worker.explore_worker.expand_prompts",
        return_value=["prompt one", "prompt two"],
    ) as mock_expand, patch(
        "worker.explore_worker.submit_to_comfyui", return_value="pid"
    ) as mock_submit, patch(
        "worker.explore_worker.wait_for_comfyui_job",
        return_value=[{"filename": "img.png", "subfolder": ""}],
    ) as mock_wait:
        keys = process_job(job, config, s3_client)

    mock_expand.assert_called_once_with(
        "a cat", 2, config.ollama_url, config.ollama_model
    )
    assert mock_submit.call_count == 2
    assert mock_wait.call_count == 2
    assert keys == [
        "explore/job-1/img.png",
        "explore/job-1/img.png",
    ]


@pytest.mark.unit
def test_process_job_generates_job_id_when_absent(tmp_path):
    """A missing job_id is filled in with a fresh uuid."""
    template_path = tmp_path / "workflow.json"
    template_path.write_text(
        '{"1": {"class_type": "KSampler", '
        '"inputs": {"positive": ["2", 0], "seed": 0}}, '
        '"2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}, '
        '"3": {"class_type": "SaveImage", '
        '"inputs": {"filename_prefix": ""}}}',
        encoding="utf-8",
    )
    config = WorkerConfig(
        queue_url="q",
        output_bucket="bucket",
        workflow_template_path=template_path,
    )
    job = {"seed_prompt": "a cat", "batch_size": 1}
    s3_client = MagicMock()

    with patch(
        "worker.explore_worker.expand_prompts", return_value=["prompt"]
    ), patch(
        "worker.explore_worker.submit_to_comfyui", return_value="pid"
    ), patch(
        "worker.explore_worker.wait_for_comfyui_job",
        return_value=[{"filename": "img.png", "subfolder": ""}],
    ):
        keys = process_job(job, config, s3_client)

    assert len(keys) == 1
    assert keys[0].startswith("explore/")
    assert keys[0].endswith("/img.png")
    assert "explore/None/" not in keys[0]


@pytest.mark.unit
def test_poll_queue_processes_and_deletes_one_message():
    """A received message is processed then deleted from the queue."""
    config = WorkerConfig(queue_url="q-url", output_bucket="bucket")
    sqs_client = MagicMock()
    s3_client = MagicMock()
    sqs_client.receive_message.side_effect = [
        {
            "Messages": [
                {
                    "Body": '{"seed_prompt": "cat", "batch_size": 1}',
                    "ReceiptHandle": "rh-1",
                    "MessageId": "m-1",
                }
            ]
        },
        StopIteration,
    ]

    with patch(
        "worker.explore_worker.process_job", return_value=["key"]
    ) as mock_process:
        with pytest.raises(StopIteration):
            poll_queue(config, sqs_client, s3_client)

    mock_process.assert_called_once()
    sqs_client.delete_message.assert_called_once_with(
        QueueUrl="q-url", ReceiptHandle="rh-1"
    )


@pytest.mark.unit
def test_poll_queue_leaves_message_on_processing_failure():
    """A processing exception skips delete_message, leaving it for redelivery."""
    config = WorkerConfig(queue_url="q-url", output_bucket="bucket")
    sqs_client = MagicMock()
    s3_client = MagicMock()
    sqs_client.receive_message.side_effect = [
        {
            "Messages": [
                {
                    "Body": '{"seed_prompt": "cat", "batch_size": 1}',
                    "ReceiptHandle": "rh-1",
                    "MessageId": "m-1",
                }
            ]
        },
        StopIteration,
    ]

    with patch(
        "worker.explore_worker.process_job",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(StopIteration):
            poll_queue(config, sqs_client, s3_client)

    sqs_client.delete_message.assert_not_called()


@pytest.mark.unit
def test_poll_queue_skips_delete_when_no_messages_received():
    """An empty receive result loops again without deleting anything."""
    config = WorkerConfig(queue_url="q-url", output_bucket="bucket")
    sqs_client = MagicMock()
    s3_client = MagicMock()
    sqs_client.receive_message.side_effect = [{"Messages": []}, StopIteration]

    with pytest.raises(StopIteration):
        poll_queue(config, sqs_client, s3_client)

    sqs_client.delete_message.assert_not_called()
