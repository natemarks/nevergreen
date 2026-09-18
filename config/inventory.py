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

from config.helper import APP_NAME, check_app_env, check_aws_account
from config.registry import STACKS_BY_ENV
from config.settings import EnvironmentSetting, get_actual_path
from stack.app_vpc import AppVpcInput, AppVpcStack
from stack.secure_s3 import SecureS3Input, SecureS3Stack
from stack.simple_asg import SimpleAsgInput, SimpleAsgStack
from stack.simple_s3 import SimpleS3Input, SimpleS3Stack
from stack.sqs_queue import SqsQueueInput, SqsQueueStack


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

    def _deploy_gpu_worker(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        app: App,
        cdk_env: Environment,
        stack_id: str,
        images_stack_id: str,
        queue_stack_id: str,
    ) -> SimpleAsgStack:
        """Create and return one GPU worker stack.

        AppVpc, the images SimpleS3 stack, and the explore SqsQueue stack
        must already be deployed: the worker reuses AppVpc for VPC/subnet
        context (like simple_asg), and gets the images bucket's read-write
        managed policy plus the queue's consumer managed policy attached to
        its instance role.
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
        env_file = "\n".join(
            [
                f"QUEUE_URL={queue_stack.queue.queue_url}",
                f"OUTPUT_BUCKET={images_stack.bucket.bucket_name}",
                f"AWS_REGION={self.environment_setting.default_region}",
            ]
        )
        return SimpleAsgStack(
            scope=app,
            cdk_env=cdk_env,
            s_input=s_input,
            app_vpc_stack=app_vpc_stack,
            managed_policies=[
                images_stack.read_write_policy,
                queue_stack.consumer_policy,
            ],
            extra_files={
                "/opt/comfyui/explore_worker.py": repo_root
                / "worker"
                / "explore_worker.py",
                "/opt/comfyui/workflows/txt2img-example.json": repo_root
                / "workflows"
                / "txt2img-example.json",
                "/etc/default/explore-worker": env_file,
            },
            termination_protection=self.TERMINATION_PROTECTION,
        )


def get_inventory(app_env: str) -> Inventory:
    """Return the inventory object for the requested application environment."""
    return Inventory(app_env=app_env)
