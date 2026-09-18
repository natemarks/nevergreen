"""HIPAA-grade S3 bucket stack and input models.

Purpose:
- Provision a dual-layer encrypted (DSSE-KMS) S3 bucket with a dedicated CMK.
- Enforce HTTPS-only access and VPC-restricted access via bucket policy.
- Expose read and read-write IAM managed policies for application attachment.
- Optionally deploy a companion access-logging bucket, Object Lock (WORM),
  and a lifecycle expiration rule.

Flow:
- `SecureS3Input.from_config_directory` loads stack-specific settings.
- `SecureS3Stack` synthesises all resources from that input.

Customize:
- Encryption, WORM, lifecycle, logging, removal policy in
  `config/<env>/secure_s3/<stack_id>/secure_s3.json`.
- See `stack/secure_s3.md` for field reference and production checklist.
"""

from dataclasses import dataclass
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_iam as iam,
    aws_kms as kms,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from aws_cdk import Environment as cdk_environment
from constructs import Construct

from config.helper import APP_NAME
from config.settings import EnvironmentSetting, SecureS3Setting
from stack.app_vpc import AppVpcStack


@dataclass(frozen=True, kw_only=True)
class SecureS3Input:
    """Typed input payload for one SecureS3Stack instance."""

    stack_id: str
    env_setting: EnvironmentSetting
    secure_s3_setting: SecureS3Setting

    def prefix(self) -> str:
        """Return the stack/resource prefix including stack instance id."""
        return (
            f"{APP_NAME}{self.env_setting.prefix()}"
            f"SecureS3{self.stack_id.capitalize()}"
        )

    def bucket_name(self) -> str:
        """Return the physical S3 bucket name for this instance."""
        app = APP_NAME.lower()
        env = self.env_setting.app_env
        return f"{app}-{env}-{self.stack_id}"

    def logging_bucket_name(self) -> str:
        """Return the physical name for the companion logging bucket."""
        return f"{self.bucket_name()}-access-logs"

    @classmethod
    def from_config_directory(
        cls,
        data_path: Path,
        stack_id: str,
        env_setting: EnvironmentSetting | None = None,
    ) -> "SecureS3Input":
        """Build SecureS3 input from `config/<env>/secure_s3/<id>/...`."""
        return cls(
            stack_id=stack_id,
            env_setting=env_setting
            or EnvironmentSetting.from_data_path(data_path),
            secure_s3_setting=SecureS3Setting.from_data_path(
                data_path, stack_id
            ),
        )


def _removal(cfg: SecureS3Setting) -> RemovalPolicy:
    return (
        RemovalPolicy.DESTROY
        if cfg.removal_policy == "DESTROY"
        else RemovalPolicy.RETAIN
    )


def _auto_delete(cfg: SecureS3Setting) -> bool:
    # auto_delete_objects requires DESTROY and must not be used with WORM
    # (COMPLIANCE mode prevents deletion; GOVERNANCE is also discouraged)
    return cfg.removal_policy == "DESTROY" and not cfg.worm_enabled


class SecureS3Stack(Stack):
    """CDK stack that provisions a HIPAA-grade S3 bucket and related resources.

    Resources always created:
    - Customer-managed KMS key (CMK) with configurable rotation period
    - DSSE-KMS encrypted S3 bucket with versioning and bucket policy layers
    - Read and read-write IAM managed policies
    - SSM String parameter for the CMK ARN
    - CloudFormation outputs for all key resource ARNs

    Optional resources (controlled by SecureS3Setting):
    - Companion S3 access-logging bucket (enable_access_logging_bucket)
    - S3 Object Lock / WORM (worm_enabled, worm_mode, worm_retention_days)
    - S3 lifecycle expiration rule (enable_lifecycle_expiration, deletion_days)

    See specs/s3-hipaa-security.md for the security controls this stack
    encapsulates.
    """

    def __init__(  # pylint: disable=too-many-locals
        self,
        scope: Construct,
        cdk_env: cdk_environment,
        s_input: SecureS3Input,
        app_vpc_stack: AppVpcStack,
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

        cfg = s_input.secure_s3_setting
        removal = _removal(cfg)
        auto_del = _auto_delete(cfg)

        # --- CMK ---
        self.cmk = kms.Key(
            self,
            f"{self._prefix}Cmk",
            description=f"CMK for {s_input.bucket_name()} SecureS3 bucket",
            enable_key_rotation=True,
            rotation_period=Duration.days(cfg.rotation_period_days),
            removal_policy=removal,
        )

        # --- Optional companion logging bucket (created before primary) ---
        self.logging_bucket: s3.Bucket | None = None
        if cfg.enable_access_logging_bucket:
            self.logging_bucket = s3.Bucket(
                self,
                f"{self._prefix}LoggingBucket",
                bucket_name=s_input.logging_bucket_name(),
                encryption=s3.BucketEncryption.S3_MANAGED,
                versioned=True,
                removal_policy=removal,
                auto_delete_objects=auto_del,
            )

        # --- Primary bucket ---
        common_kwargs: dict = {
            "bucket_name": s_input.bucket_name(),
            "encryption": s3.BucketEncryption.DSSE,
            "encryption_key": self.cmk,
            "server_access_logs_bucket": self.logging_bucket,
            "removal_policy": removal,
            "auto_delete_objects": auto_del,
        }

        if cfg.worm_enabled:
            worm_retention = (
                s3.ObjectLockRetention.compliance(
                    Duration.days(cfg.worm_retention_days)
                )
                if cfg.worm_mode == "COMPLIANCE"
                else s3.ObjectLockRetention.governance(
                    Duration.days(cfg.worm_retention_days)
                )
            )
            self.bucket = s3.Bucket(
                self,
                f"{self._prefix}Bucket",
                object_lock_enabled=True,
                object_lock_default_retention=worm_retention,
                **common_kwargs,
            )
        else:
            self.bucket = s3.Bucket(
                self,
                f"{self._prefix}Bucket",
                versioned=True,
                **common_kwargs,
            )

        # --- Optional lifecycle expiration ---
        if cfg.enable_lifecycle_expiration:
            self.bucket.add_lifecycle_rule(
                id="ExpireObjects",
                expiration=Duration.days(cfg.deletion_days),
                noncurrent_version_expiration=Duration.days(cfg.deletion_days),
                enabled=True,
            )

        # --- Bucket policy layers ---
        endpoint_id = app_vpc_stack.s3_gateway_endpoint.vpc_endpoint_id

        self.bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyNonHttps",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[
                    self.bucket.bucket_arn,
                    f"{self.bucket.bucket_arn}/*",
                ],
                conditions={"Bool": {"aws:SecureTransport": "false"}},
            )
        )
        self.bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="EnforceDsseKms",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[f"{self.bucket.bucket_arn}/*"],
                conditions={
                    "StringNotEqualsIfExists": {
                        "s3:x-amz-server-side-encryption": "aws:kms:dsse"
                    }
                },
            )
        )
        self.bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyNonVpcEndpoint",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[
                    self.bucket.bucket_arn,
                    f"{self.bucket.bucket_arn}/*",
                ],
                conditions={
                    "StringNotEquals": {"aws:sourceVpce": endpoint_id}
                },
            )
        )

        # --- IAM access policies ---
        self.read_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}ReadPolicy",
            managed_policy_name=f"{self._prefix}-read",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["s3:GetObject", "s3:ListBucket"],
                    resources=[
                        self.bucket.bucket_arn,
                        f"{self.bucket.bucket_arn}/*",
                    ],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["kms:Decrypt"],
                    resources=[self.cmk.key_arn],
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
                    resources=[
                        self.bucket.bucket_arn,
                        f"{self.bucket.bucket_arn}/*",
                    ],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["kms:Decrypt", "kms:GenerateDataKey"],
                    resources=[self.cmk.key_arn],
                ),
            ],
        )

        # --- SSM parameters ---
        app = APP_NAME.lower()
        env = s_input.env_setting.app_env
        sid = s_input.stack_id
        ssm_cmk = ssm.StringParameter(
            self,
            f"{self._prefix}CmkArnParam",
            parameter_name=f"/{app}/{env}/secure_s3/{sid}/cmk-arn",
            string_value=self.cmk.key_arn,
            description=f"CMK ARN for {s_input.bucket_name()} SecureS3 bucket",
        )
        ssm_bucket = ssm.StringParameter(
            self,
            f"{self._prefix}BucketArnParam",
            parameter_name=f"/{app}/{env}/secure_s3/{sid}/bucket-arn",
            string_value=self.bucket.bucket_arn,
            description=(
                f"Primary bucket ARN for {s_input.bucket_name()} SecureS3 bucket"
            ),
        )

        # --- CloudFormation outputs ---
        CfnOutput(self, "BucketArn", value=self.bucket.bucket_arn)
        CfnOutput(self, "CmkArn", value=self.cmk.key_arn)
        CfnOutput(
            self,
            "ReadPolicyArn",
            value=self.read_policy.managed_policy_arn,
        )
        CfnOutput(
            self,
            "ReadWritePolicyArn",
            value=self.read_write_policy.managed_policy_arn,
        )
        CfnOutput(self, "CmkArnSsmPath", value=ssm_cmk.parameter_name)
        CfnOutput(self, "BucketArnSsmPath", value=ssm_bucket.parameter_name)
        if self.logging_bucket is not None:
            ssm_logging = ssm.StringParameter(
                self,
                f"{self._prefix}LoggingBucketArnParam",
                parameter_name=(
                    f"/{app}/{env}/secure_s3/{sid}/logging-bucket-arn"
                ),
                string_value=self.logging_bucket.bucket_arn,
                description=(
                    f"Access-logging bucket ARN for "
                    f"{s_input.bucket_name()} SecureS3 bucket"
                ),
            )
            CfnOutput(
                self,
                "LoggingBucketArn",
                value=self.logging_bucket.bucket_arn,
            )
            CfnOutput(
                self,
                "LoggingBucketArnSsmPath",
                value=ssm_logging.parameter_name,
            )

        # --- Stack-instance tag for Resource Groups discovery ---
        Tags.of(self).add("secure_s3_id", s_input.stack_id)
