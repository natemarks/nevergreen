"""SQS job queue stack and input models.

Purpose:
- Provision a standard SQS queue plus its dead-letter queue, for a
  worker-consumed job queue (e.g. explore-a-queue, research/
  aws-infrastructure.md's Phase 1 decision).
- Expose consumer (receive/delete) and producer (send) IAM managed
  policies for application attachment.

Flow:
- `SqsQueueInput.from_config_directory` loads stack-specific settings.
- `SqsQueueStack` synthesises the queue + DLQ from that input.

Customize:
- Visibility timeout and max receive count in
  `config/<env>/sqs_queue/<stack_id>/sqs_queue.json`.
"""

# pylint: disable=duplicate-code
# Shares the Input/prefix()/__init__ constructor shape with the other stack
# modules (e.g. stack/secure_s3.py) by design (see DESIGN.md's Stack
# Deployment section) — not accidental duplication to refactor.
from dataclasses import dataclass
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_iam as iam, aws_sqs as sqs
from aws_cdk import Environment as cdk_environment
from constructs import Construct

from config.helper import APP_NAME
from config.settings import EnvironmentSetting, SqsQueueSetting


@dataclass(frozen=True, kw_only=True)
class SqsQueueInput:
    """Typed input payload for one SqsQueueStack instance."""

    stack_id: str
    env_setting: EnvironmentSetting
    queue_setting: SqsQueueSetting

    def prefix(self) -> str:
        """Return the stack/resource prefix including stack instance id."""
        return (
            f"{APP_NAME}{self.env_setting.prefix()}"
            f"SqsQueue{self.stack_id.capitalize()}"
        )

    def queue_name(self) -> str:
        """Return the physical queue name for this instance."""
        app = APP_NAME.lower()
        env = self.env_setting.app_env
        return f"{app}-{env}-{self.stack_id}-queue"

    @classmethod
    def from_config_directory(
        cls,
        data_path: Path,
        stack_id: str,
        env_setting: EnvironmentSetting | None = None,
    ) -> "SqsQueueInput":
        """Build SqsQueue input from `config/<env>/sqs_queue/<id>/...`."""
        return cls(
            stack_id=stack_id,
            env_setting=env_setting
            or EnvironmentSetting.from_data_path(data_path),
            queue_setting=SqsQueueSetting.from_data_path(data_path, stack_id),
        )


class SqsQueueStack(Stack):
    """CDK stack that provisions one SQS queue and its dead-letter queue.

    Resources always created:
    - A dead-letter queue (same visibility timeout, default 4-day retention)
    - The primary queue, redriving to the DLQ after `max_receive_count`
      failed receives
    - Consumer (receive/delete) and producer (send) IAM managed policies
    """

    def __init__(
        self,
        scope: Construct,
        cdk_env: cdk_environment,
        s_input: SqsQueueInput,
        **kwargs,
    ):
        self.s_input = s_input
        self._prefix = s_input.prefix()
        super().__init__(
            scope=scope,
            id=f"{self._prefix}Stack",
            env=cdk_env,
            **kwargs,
        )

        cfg = s_input.queue_setting
        visibility_timeout = Duration.seconds(cfg.visibility_timeout_seconds)

        self.dead_letter_queue = sqs.Queue(
            self,
            f"{self._prefix}Dlq",
            queue_name=f"{s_input.queue_name()}-dlq",
            visibility_timeout=visibility_timeout,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.queue = sqs.Queue(
            self,
            f"{self._prefix}Queue",
            queue_name=s_input.queue_name(),
            visibility_timeout=visibility_timeout,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=cfg.max_receive_count,
                queue=self.dead_letter_queue,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.consumer_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}ConsumerPolicy",
            managed_policy_name=f"{self._prefix}-consumer",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes",
                    ],
                    resources=[self.queue.queue_arn],
                ),
            ],
        )
        self.producer_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}ProducerPolicy",
            managed_policy_name=f"{self._prefix}-producer",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["sqs:SendMessage", "sqs:GetQueueAttributes"],
                    resources=[self.queue.queue_arn],
                ),
            ],
        )

        CfnOutput(self, "QueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "QueueArn", value=self.queue.queue_arn)
        CfnOutput(
            self, "DeadLetterQueueUrl", value=self.dead_letter_queue.queue_url
        )
        CfnOutput(
            self,
            "ConsumerPolicyArn",
            value=self.consumer_policy.managed_policy_arn,
        )
        CfnOutput(
            self,
            "ProducerPolicyArn",
            value=self.producer_policy.managed_policy_arn,
        )

        Tags.of(self).add("sqs_queue_id", s_input.stack_id)
