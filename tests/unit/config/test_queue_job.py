"""Tests for config.queue_job."""

# pylint: disable=redefined-outer-name
import json
from unittest.mock import MagicMock, patch

import pytest

from config.queue_job import send_job
from tests.unit.config._shared import (
    write_environment_json as _write_environment_json,
    write_sqs_queue_config as _write_sqs_queue_config,
)


@pytest.fixture
def data_path(tmp_path):
    """Return a tmp data path with environment.json and an explore-a queue."""
    _write_environment_json(tmp_path)
    _write_sqs_queue_config(tmp_path, "explore-a")
    return tmp_path


@pytest.mark.unit
def test_send_job_sends_body_to_the_resolved_queue_url(data_path):
    """send_job resolves the queue's physical name into its real URL."""
    sqs = MagicMock()
    sqs.get_queue_url.return_value = {
        "QueueUrl": (
            "https://sqs.us-east-1.amazonaws.com/123456789012/"
            "nevergreen-dev-explore-a-queue"
        )
    }

    with patch("config.queue_job.check_aws_account"), patch(
        "config.queue_job.get_actual_path", return_value=data_path
    ):
        job_id = send_job(
            "dev", "a fox exploring a neon city", 3, sqs_client=sqs
        )

    sqs.get_queue_url.assert_called_once_with(
        QueueName="nevergreen-dev-explore-a-queue"
    )
    sqs.send_message.assert_called_once()
    call = sqs.send_message.call_args
    assert call.kwargs["QueueUrl"] == (
        "https://sqs.us-east-1.amazonaws.com/123456789012/"
        "nevergreen-dev-explore-a-queue"
    )
    body = json.loads(call.kwargs["MessageBody"])
    assert body == {
        "seed_prompt": "a fox exploring a neon city",
        "batch_size": 3,
        "job_id": job_id,
    }


@pytest.mark.unit
def test_send_job_generates_a_job_id_when_absent(data_path):
    """A job_id is generated and returned when the caller supplies none."""
    sqs = MagicMock()
    sqs.get_queue_url.return_value = {"QueueUrl": "https://example/queue"}

    with patch("config.queue_job.check_aws_account"), patch(
        "config.queue_job.get_actual_path", return_value=data_path
    ):
        job_id = send_job("dev", "seed", 1, sqs_client=sqs)

    assert job_id
    body = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert body["job_id"] == job_id


@pytest.mark.unit
def test_send_job_uses_the_given_job_id(data_path):
    """A caller-supplied job_id is used verbatim, not overwritten."""
    sqs = MagicMock()
    sqs.get_queue_url.return_value = {"QueueUrl": "https://example/queue"}

    with patch("config.queue_job.check_aws_account"), patch(
        "config.queue_job.get_actual_path", return_value=data_path
    ):
        job_id = send_job("dev", "seed", 1, job_id="my-job-id", sqs_client=sqs)

    assert job_id == "my-job-id"
    body = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert body["job_id"] == "my-job-id"
