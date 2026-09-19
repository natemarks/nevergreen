#!/usr/bin/env python3
"""Environment-specific stack inventory for the CDK app.

Purpose:
- Select stacks to deploy per environment.
- Apply shared environment tags.
- Enforce stack dependency order via STACKS_BY_ENV in config/registry.py.

Flow:
- `get_inventory(app_env)` returns an `Inventory` instance.
- `Inventory.deploy_stacks` iterates STACKS_BY_ENV[app_env] and calls each
  factory's deploy callable in order, storing returned stacks in `_deployed`.

Customize:
- Add or reorder stacks in `config/registry.py`.
- Enable termination protection by setting TERMINATION_PROTECTION = True on
  a subclass or directly on the instance before calling deploy_stacks.
- Extend shared tags in `set_environment_tags`.
"""

from pathlib import Path
from typing import ClassVar, cast

from aws_cdk import App, Environment, Stack, Tags
from aws_cdk import aws_iam as iam
from aws_cdk.aws_autoscaling import CfnScalingPolicy
from constructs import Construct

from config.helper import APP_NAME, check_app_env, check_aws_account
from config.registry import STACKS_BY_ENV
from config.settings import EnvironmentSetting, get_actual_path
from stack.app_vpc import AppVpcInput, AppVpcStack
from stack.ecr_repo import EcrRepoInput, EcrRepoStack
from stack.secure_s3 import SecureS3Input, SecureS3Stack
from stack.simple_asg import SimpleAsgInput, SimpleAsgStack
from stack.simple_s3 import SimpleS3Input, SimpleS3Stack
from stack.sqs_queue import SqsQueueInput, SqsQueueStack

SQS_BACKLOG_PER_INSTANCE_TARGET = 2


def _metric_data_query(
    query_id: str,
    metric_name: str,
    namespace: str,
    dimension_name: str,
    dimension_value: str,
) -> CfnScalingPolicy.TargetTrackingMetricDataQueryProperty:
    """One metric-data-query feeding a target-tracking metric-math
    expression -- a single CloudWatch metric, referenced by `query_id`
    from the expression that combines it with others.
    """
    metric = CfnScalingPolicy.MetricProperty(
        metric_name=metric_name,
        namespace=namespace,
        dimensions=[
            CfnScalingPolicy.MetricDimensionProperty(
                name=dimension_name, value=dimension_value
            )
        ],
    )
    stat = CfnScalingPolicy.TargetTrackingMetricStatProperty(
        metric=metric, stat="Average"
    )
    return CfnScalingPolicy.TargetTrackingMetricDataQueryProperty(
        id=query_id, metric_stat=stat, return_data=False
    )


def _sqs_backlog_scaling_policy(
    scope: Construct, asg_name: str, queue_name: str, target_value: int
) -> CfnScalingPolicy:
    """Attach a target-tracking policy on SQS backlog-per-instance.

    AWS's own documented pattern for scaling an ASG from 0 on queue depth
    has no predefined ASG metric, so it needs a metric-math expression.
    CDK's L2 `scale_to_track_metric` only accepts a single direct metric
    ("DirectMetricsSupportedTargetTracking", confirmed synthesizing this),
    so this uses the L1 CfnScalingPolicy directly -- it maps straight onto
    the real `TargetTrackingConfiguration.CustomizedMetricSpecification.
    Metrics` API (a list of metric data queries), exactly what
    CloudWatch's own console produces for a metric-math target-tracking
    policy. `GroupInServiceInstances` requires the ASG's
    `enable_group_metrics=True` to actually be published.
    """
    backlog = _metric_data_query(
        "backlog",
        "ApproximateNumberOfMessagesVisible",
        "AWS/SQS",
        "QueueName",
        queue_name,
    )
    instances = _metric_data_query(
        "instances",
        "GroupInServiceInstances",
        "AWS/AutoScaling",
        "AutoScalingGroupName",
        asg_name,
    )
    backlog_per_instance = (
        CfnScalingPolicy.TargetTrackingMetricDataQueryProperty(
            id="backlog_per_instance",
            expression="IF(instances > 0, backlog / instances, backlog)",
            return_data=True,
        )
    )
    target_tracking = CfnScalingPolicy.TargetTrackingConfigurationProperty(
        target_value=target_value,
        customized_metric_specification=(
            CfnScalingPolicy.CustomizedMetricSpecificationProperty(
                metrics=[backlog, instances, backlog_per_instance]
            )
        ),
    )
    return CfnScalingPolicy(
        scope,
        "SqsBacklogPerInstance",
        auto_scaling_group_name=asg_name,
        policy_type="TargetTrackingScaling",
        target_tracking_configuration=target_tracking,
    )


class Inventory:
    """Inventory of stacks for one application environment.

    deploy_stacks iterates STACKS_BY_ENV[app_env] in order. Each factory's
    deploy callable receives this Inventory instance so it can access the
    _deployed registry for cross-stack dependencies.
    """

    TERMINATION_PROTECTION: ClassVar[bool] = False

    def __init__(self, app_env: str):
        """Validate environment/account and load environment settings."""
        check_app_env(app_env)
        check_aws_account(app_env)
        self.data_path = get_actual_path(app_env)
        self.app_env = app_env
        self._deployed: dict[str, Stack] = {}
        self.environment_setting = EnvironmentSetting.from_data_path(
            self.data_path
        )

    def deploy_stacks(self, app: App, cdk_env: Environment) -> None:
        """Deploy stacks in STACKS_BY_ENV order for this environment."""
        for factory in STACKS_BY_ENV[self.app_env]:
            stack = factory.deploy(self, app, cdk_env)
            self._deployed[stack.stack_name] = stack

    def _get_deployed(self, stack_name: str) -> Stack:
        """Return a previously-deployed stack by name, or raise RuntimeError."""
        if stack_name not in self._deployed:
            raise RuntimeError(
                f"Stack '{stack_name}' not found in deployed registry. "
                "Check list order in STACKS_BY_ENV in config/registry.py."
            )
        return self._deployed[stack_name]

    def set_environment_tags(self, app: App) -> None:
        """Apply shared environment tags to all stacks in the app."""
        Tags.of(app).add("env_id", self.app_env)
        Tags.of(app).add("app_env", self.app_env)
        Tags.of(app).add("Environment", self.app_env)

    def _deploy_app_vpc(self, app: App, cdk_env: Environment) -> AppVpcStack:
        """Create and return the AppVpc stack."""
        s_input = AppVpcInput.from_config_directory(
            self.data_path, env_setting=self.environment_setting
        )
        return AppVpcStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_simple_asg(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> SimpleAsgStack:
        """Create and return one SimpleAsg stack.

        AppVpc must already be deployed because SimpleAsg consumes the VPC.
        """
        app_vpc_name = (
            f"{APP_NAME}{self.environment_setting.prefix()}AppVpcStack"
        )
        app_vpc_stack = cast(AppVpcStack, self._get_deployed(app_vpc_name))
        s_input = SimpleAsgInput.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        return SimpleAsgStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            app_vpc_stack=app_vpc_stack,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_secure_s3(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> SecureS3Stack:
        """Create and return one SecureS3 stack.

        AppVpc must already be deployed because SecureS3 enforces VPC endpoint
        access via the gateway endpoint created in AppVpcStack.
        """
        app_vpc_name = (
            f"{APP_NAME}{self.environment_setting.prefix()}AppVpcStack"
        )
        app_vpc_stack = cast(AppVpcStack, self._get_deployed(app_vpc_name))
        s_input = SecureS3Input.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        return SecureS3Stack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            app_vpc_stack=app_vpc_stack,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_simple_s3(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> SimpleS3Stack:
        """Create and return one SimpleS3 stack (no AppVpc dependency)."""
        s_input = SimpleS3Input.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        return SimpleS3Stack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_sqs_queue(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> SqsQueueStack:
        """Create and return one SqsQueue stack (no AppVpc dependency)."""
        s_input = SqsQueueInput.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        return SqsQueueStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_ecr_repo(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> EcrRepoStack:
        """Create and return one EcrRepo stack (no AppVpc dependency)."""
        s_input = EcrRepoInput.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        return EcrRepoStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            termination_protection=self.TERMINATION_PROTECTION,
        )

    def _deploy_gpu_worker(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        app: App,
        cdk_env: Environment,
        stack_id: str,
        images_stack_id: str,
        queue_stack_id: str,
        models_stack_id: str,
        ecr_repo_stack_id: str | None,
    ) -> SimpleAsgStack:
        """Create and return one GPU worker stack.

        AppVpc, the images SimpleS3 stack, the explore SqsQueue stack, and
        the models SimpleS3 stack must already be deployed: the worker
        reuses AppVpc for VPC/subnet context (like simple_asg), and gets
        the images bucket's read-write managed policy, the queue's
        consumer managed policy, and the models bucket's read managed
        policy (so userdata can `aws s3 sync` checkpoints down at boot)
        attached to its instance role.

        If `ecr_repo_stack_id` is given (Phase 2, wayfinder ticket #29),
        the named EcrRepo stack must also already be deployed: its pull
        policy is attached, the container image URI is passed through the
        env file, `explore_worker.py`/the workflow template are no longer
        delivered via extra_files (Phase 2's image bundles its own copy),
        and a target-tracking scaling policy on SQS backlog-per-instance
        is attached to the ASG.
        """
        app_vpc_name = (
            f"{APP_NAME}{self.environment_setting.prefix()}AppVpcStack"
        )
        app_vpc_stack = cast(AppVpcStack, self._get_deployed(app_vpc_name))
        images_input = SimpleS3Input.from_config_directory(
            self.data_path,
            images_stack_id,
            env_setting=self.environment_setting,
        )
        images_stack = cast(
            SimpleS3Stack,
            self._get_deployed(f"{images_input.prefix()}Stack"),
        )
        models_input = SimpleS3Input.from_config_directory(
            self.data_path,
            models_stack_id,
            env_setting=self.environment_setting,
        )
        models_stack = cast(
            SimpleS3Stack,
            self._get_deployed(f"{models_input.prefix()}Stack"),
        )
        queue_input = SqsQueueInput.from_config_directory(
            self.data_path,
            queue_stack_id,
            env_setting=self.environment_setting,
        )
        queue_stack = cast(
            SqsQueueStack,
            self._get_deployed(f"{queue_input.prefix()}Stack"),
        )
        s_input = SimpleAsgInput.from_config_directory(
            self.data_path,
            stack_id,
            env_setting=self.environment_setting,
        )
        repo_root = Path(__file__).parent.parent

        env_lines = [
            f"QUEUE_URL={queue_stack.queue.queue_url}",
            f"OUTPUT_BUCKET={images_stack.bucket.bucket_name}",
            f"MODELS_BUCKET={models_stack.bucket.bucket_name}",
            f"AWS_REGION={self.environment_setting.default_region}",
        ]
        managed_policies: list[iam.IManagedPolicy] = [
            images_stack.read_write_policy,
            queue_stack.consumer_policy,
            models_stack.read_policy,
        ]
        extra_files: dict[str, Path | str] = {
            "/opt/comfyui/explore_worker.py": repo_root
            / "worker"
            / "explore_worker.py",
            "/opt/comfyui/workflows/txt2img-example.json": repo_root
            / "workflows"
            / "txt2img-example.json",
        }

        ecr_stack = None
        if ecr_repo_stack_id is not None:
            ecr_input = EcrRepoInput.from_config_directory(
                self.data_path,
                ecr_repo_stack_id,
                env_setting=self.environment_setting,
            )
            ecr_stack = cast(
                EcrRepoStack,
                self._get_deployed(f"{ecr_input.prefix()}Stack"),
            )
            managed_policies.append(ecr_stack.pull_policy)
            env_lines.append(
                f"CONTAINER_IMAGE_URI={ecr_stack.repository.repository_uri}"
            )
            # Phase 2's worker image bundles its own copy of
            # explore_worker.py/the workflow template -- extra_files would
            # just be dead weight on a containerized instance. It still
            # needs refresh_worker.sh though: the periodic timer and
            # `make force_refresh` (over SSM) both run it on the host,
            # outside the container.
            extra_files = {
                "/opt/comfyui/bin/refresh_worker.sh": repo_root
                / "worker"
                / "refresh_worker.sh",
            }

        extra_files["/etc/default/explore-worker"] = "\n".join(env_lines)

        stack = SimpleAsgStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            app_vpc_stack=app_vpc_stack,
            managed_policies=managed_policies,
            extra_files=extra_files,
            enable_group_metrics=ecr_stack is not None,
            termination_protection=self.TERMINATION_PROTECTION,
        )

        if ecr_stack is not None:
            _sqs_backlog_scaling_policy(
                stack,
                stack.asg.auto_scaling_group_name,
                queue_stack.s_input.queue_name(),
                SQS_BACKLOG_PER_INSTANCE_TARGET,
            )

        return stack


def get_inventory(app_env: str) -> Inventory:
    """Return the inventory object for the requested application environment."""
    return Inventory(app_env=app_env)
