"""ECR repository stack and input models.

Purpose:
- Provision one ECR repository for a containerized worker image (Phase 2,
  wayfinder ticket #29). The image itself is built and pushed outside
  `cdk deploy` -- see `config/build_worker_image.py` -- this stack only
  owns the repository resource and its pull policy.
- Expose a pull IAM managed policy for gpu_worker instance roles.

Flow:
- `EcrRepoInput.from_config_directory` loads stack-specific settings.
- `EcrRepoStack` synthesises the repository from that input.

Customize:
- Image scan on push, lifecycle max image count, and removal policy in
  `config/<env>/ecr_repo/<stack_id>/ecr_repo.json`.
"""

# pylint: disable=duplicate-code
# Shares the Input/prefix()/__init__ constructor shape with the other
# stack modules (e.g. stack/secure_s3.py) by design (see DESIGN.md's Stack
# Deployment section) -- not accidental duplication to refactor.
from dataclasses import dataclass
from pathlib import Path

from aws_cdk import CfnOutput, RemovalPolicy, Stack, Tags
from aws_cdk import aws_ecr as ecr, aws_iam as iam
from aws_cdk import Environment as cdk_environment
from constructs import Construct

from config.helper import APP_NAME
from config.settings import EcrRepoSetting, EnvironmentSetting


@dataclass(frozen=True, kw_only=True)
class EcrRepoInput:
    """Typed input payload for one EcrRepoStack instance."""

    stack_id: str
    env_setting: EnvironmentSetting
    ecr_repo_setting: EcrRepoSetting

    def prefix(self) -> str:
        """Return the stack/resource prefix including stack instance id."""
        return (
            f"{APP_NAME}{self.env_setting.prefix()}"
            f"EcrRepo{self.stack_id.capitalize()}"
        )

    def repository_name(self) -> str:
        """Return the physical ECR repository name for this instance."""
        app = APP_NAME.lower()
        env = self.env_setting.app_env
        return f"{app}-{env}-{self.stack_id}"

    @classmethod
    def from_config_directory(
        cls,
        data_path: Path,
        stack_id: str,
        env_setting: EnvironmentSetting | None = None,
    ) -> "EcrRepoInput":
        """Build EcrRepo input from `config/<env>/ecr_repo/<id>/...`."""
        return cls(
            stack_id=stack_id,
            env_setting=env_setting
            or EnvironmentSetting.from_data_path(data_path),
            ecr_repo_setting=EcrRepoSetting.from_data_path(
                data_path, stack_id
            ),
        )


class EcrRepoStack(Stack):
    """CDK stack that provisions one ECR repository.

    Resources always created:
    - The repository, with a lifecycle rule expiring images beyond
      `max_image_count`
    - A pull IAM managed policy (get-download-url, batch-get-image,
      batch-check-layer-availability, plus the account-level
      get-authorization-token every `docker pull`/`docker login` needs)
    """

    def __init__(
        self,
        scope: Construct,
        cdk_env: cdk_environment,
        s_input: EcrRepoInput,
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

        cfg = s_input.ecr_repo_setting
        removal = (
            RemovalPolicy.DESTROY
            if cfg.removal_policy == "DESTROY"
            else RemovalPolicy.RETAIN
        )

        self.repository = ecr.Repository(
            self,
            f"{self._prefix}Repository",
            repository_name=s_input.repository_name(),
            image_scan_on_push=cfg.image_scan_on_push,
            removal_policy=removal,
            empty_on_delete=cfg.removal_policy == "DESTROY",
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Expire images beyond max_image_count",
                    max_image_count=cfg.max_image_count,
                )
            ],
        )

        self.pull_policy = iam.ManagedPolicy(
            self,
            f"{self._prefix}PullPolicy",
            managed_policy_name=f"{self._prefix}-pull",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:BatchCheckLayerAvailability",
                    ],
                    resources=[self.repository.repository_arn],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["ecr:GetAuthorizationToken"],
                    resources=["*"],
                ),
            ],
        )

        CfnOutput(self, "RepositoryUri", value=self.repository.repository_uri)
        CfnOutput(self, "RepositoryArn", value=self.repository.repository_arn)
        CfnOutput(
            self, "PullPolicyArn", value=self.pull_policy.managed_policy_arn
        )

        Tags.of(self).add("ecr_repo_id", s_input.stack_id)
