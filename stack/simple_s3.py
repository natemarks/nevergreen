"""Simple S3 bucket stack and input models.

Purpose:
- Provision a plain, S3-managed-encrypted bucket without the VPC/audit/WORM
  controls `secure_s3.py` enforces, for content that doesn't need them.
- Enforce HTTPS-only access.
- Expose read and read-write IAM managed policies for application attachment.

Flow:
- `SimpleS3Input.from_config_directory` loads stack-specific settings.
- `SimpleS3Stack` synthesises all resources from that input.

Customize:
- Lifecycle expiration and removal policy in
  `config/<env>/simple_s3/<stack_id>/simple_s3.json`.
- If a bucket later needs `secure_s3`'s VPC-restriction/WORM/CMK controls,
  move its `StackFactory` entry to `secure_s3` in `config/registry.py`
  instead of adding those controls here.
"""

# pylint: disable=duplicate-code
# Shares bucket-policy/IAM-policy/SSM-parameter shape with stack/secure_s3.py
# by design (see module docstring) — not accidental duplication to refactor.
from dataclasses import dataclass
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_iam as iam,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from aws_cdk import Environment as cdk_environment
from constructs import Construct

from config.helper import APP_NAME
from config.settings import EnvironmentSetting, SimpleS3Setting


@dataclass(frozen=True, kw_only=True)
class SimpleS3Input:
    """Typed input payload for one SimpleS3Stack instance."""

    stack_id: str
    env_setting: EnvironmentSetting
    simple_s3_setting: SimpleS3Setting

    def prefix(self) -> str:
        """Return the stack/resource prefix including stack instance id."""
        return (
            f"{APP_NAME}{self.env_setting.prefix()}"
            f"SimpleS3{self.stack_id.capitalize()}"
        )

    def bucket_name(self) -> str:
        """Return the physical S3 bucket name for this instance."""
        app = APP_NAME.lower()
        env = self.env_setting.app_env
        return f"{app}-{env}-{self.stack_id}"

    @classmethod
    def from_config_directory(
        cls,
        data_path: Path,
        stack_id: str,
        env_setting: EnvironmentSetting | None = None,
    ) -> "SimpleS3Input":
        """Build SimpleS3 input from `config/<env>/simple_s3/<id>/...`."""
        return cls(
            stack_id=stack_id,
            env_setting=env_setting
            or EnvironmentSetting.from_data_path(data_path),
            simple_s3_setting=SimpleS3Setting.from_data_path(
                data_path, stack_id
            ),
        )


def _removal(cfg: SimpleS3Setting) -> RemovalPolicy:
    return (
        RemovalPolicy.DESTROY
        if cfg.removal_policy == "DESTROY"
        else RemovalPolicy.RETAIN
    )


class SimpleS3Stack(Stack):
    """CDK stack that provisions a plain, S3-managed-encrypted bucket.

    Resources always created:
    - S3-managed-encrypted (SSE-S3) bucket with versioning
    - HTTPS-only bucket policy statement
    - Read and read-write IAM managed policies
    - SSM String parameter for the bucket ARN
    - CloudFormation outputs for key resource ARNs

    Optional resources (controlled by SimpleS3Setting):
    - S3 lifecycle expiration rule (enable_lifecycle_expiration, deletion_days)

    Deliberately does not provide a CMK/DSSE-KMS, a companion access-logging
    bucket, WORM/Object Lock, or VPC-endpoint-restricted access — see
    `stack/secure_s3.py` for those controls. No `AppVpcStack` dependency for
    the same reason.
    """

    def __init__(
        self,
        scope: Construct,
        cdk_env: cdk_environment,
        s_input: SimpleS3Input,
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

        cfg = s_input.simple_s3_setting
        removal = _removal(cfg)
        auto_delete = cfg.removal_policy == "DESTROY"

        self.bucket = s3.Bucket(
            self,
            f"{self._prefix}Bucket",
            bucket_name=s_input.bucket_name(),
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=removal,
            auto_delete_objects=auto_delete,
        )

        if cfg.enable_lifecycle_expiration:
            self.bucket.add_lifecycle_rule(
                id="ExpireObjects",
                expiration=Duration.days(cfg.deletion_days),
                noncurrent_version_expiration=Duration.days(cfg.deletion_days),
                enabled=True,
            )

        bucket_arn = self.bucket.bucket_arn
        bucket_arn_wildcard = f"{bucket_arn}/*"

        self.bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyNonHttps",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[bucket_arn, bucket_arn_wildcard],
                conditions={"Bool": {"aws:SecureTransport": "false"}},
            )
        )

        self.read_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}ReadPolicy",
            managed_policy_name=f"{self._prefix}-read",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["s3:GetObject", "s3:ListBucket"],
                    resources=[bucket_arn, bucket_arn_wildcard],
                ),
            ],
        )
        self.read_write_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}ReadWritePolicy",
            managed_policy_name=f"{self._prefix}-read-write",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "s3:GetObject",
                        "s3:ListBucket",
                        "s3:PutObject",
                        "s3:DeleteObject",
                    ],
                    resources=[bucket_arn, bucket_arn_wildcard],
                ),
            ],
        )

        app = APP_NAME.lower()
        env = s_input.env_setting.app_env
        sid = s_input.stack_id
        ssm_prefix = f"/{app}/{env}/simple_s3/{sid}"
        ssm_bucket = ssm.StringParameter(
            self,
            f"{self._prefix}BucketArnParam",
            parameter_name=f"{ssm_prefix}/bucket-arn",
            string_value=self.bucket.bucket_arn,
            description=(
                f"Primary bucket ARN for {s_input.bucket_name()} "
                "SimpleS3 bucket"
            ),
        )

        CfnOutput(self, "BucketArn", value=self.bucket.bucket_arn)
        CfnOutput(
            self, "ReadPolicyArn", value=self.read_policy.managed_policy_arn
        )
        CfnOutput(
            self,
            "ReadWritePolicyArn",
            value=self.read_write_policy.managed_policy_arn,
        )
        CfnOutput(self, "BucketArnSsmPath", value=ssm_bucket.parameter_name)

        Tags.of(self).add("simple_s3_id", s_input.stack_id)
