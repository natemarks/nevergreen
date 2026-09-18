#!/usr/bin/env python3
"""Scale simple_asg-based Auto Scaling Groups up or down.

Purpose:
- Read min/max straight from each simple_asg instance's own settings
  (config/<env>/simple_asg/<id>/simple_asg.json) -- the same
  JsonSettingBase path every stack already uses, so there's no separate
  source of truth to drift out of sync.
- "down": min=max=desired=0 for every matching Auto Scaling Group.
- "up": min/max from config; desired = min, reproducing SimpleAsgStack's
  own behavior (it never sets desired_capacity, so CDK's documented
  default -- minCapacity, left unchanged on later deploys -- applies).

Why not just `cdk deploy` to undo "down": CloudFormation only pushes
property changes relative to the *previously deployed template*, not
relative to live AWS state. Since min/max_instances don't change in config
between a scale-down and a redeploy, CloudFormation sees no diff and never
re-asserts them -- it does not self-heal drift caused by calling the Auto
Scaling API directly, which is exactly what this module does.

Flow:
- Parse direction ("up"/"down") and environment from CLI args.
- AsgScaler discovers every config/<env>/simple_asg/<id>/ directory,
  resolves each one's real AutoScalingGroup via its CloudFormation stack,
  and calls the Auto Scaling API directly.

Customize:
- Add new simple_asg-based (or gpu_worker, which reuses simple_asg)
  instances under config/<env>/simple_asg/<id>/ and this picks them up
  automatically -- no code change needed here.
"""

import argparse

import boto3
from botocore.exceptions import ClientError

from config.helper import check_app_env, check_aws_account, get_logger
from config.project import SUPPORTED_APP_ENVS
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_asg import SimpleAsgInput

mlog = get_logger(str(__name__))


class AsgScaler:
    """Scales every simple_asg-based Auto Scaling Group in one environment."""

    def __init__(self, app_env: str, cfn_client=None, autoscaling_client=None):
        """Validate environment/account and set up AWS clients."""
        check_app_env(app_env)
        check_aws_account(app_env)
        self.app_env = app_env
        self.data_path = get_actual_path(app_env)
        self.env_setting = EnvironmentSetting.from_data_path(self.data_path)
        region = self.env_setting.default_region
        self.cfn = cfn_client or boto3.client(
            "cloudformation", region_name=region
        )
        self.autoscaling = autoscaling_client or boto3.client(
            "autoscaling", region_name=region
        )

    def stack_ids(self) -> list[str]:
        """Return every stack_id with a config/<env>/simple_asg/<id>/ dir."""
        simple_asg_dir = self.data_path / "simple_asg"
        if not simple_asg_dir.is_dir():
            return []
        return sorted(
            p.name
            for p in simple_asg_dir.iterdir()
            if p.is_dir() and (p / "simple_asg.json").is_file()
        )

    def _asg_name(self, stack_name: str) -> str | None:
        """Return the physical AutoScalingGroup id for one CFN stack."""
        try:
            resources = self.cfn.describe_stack_resources(
                StackName=stack_name
            )["StackResources"]
        except ClientError:
            mlog.warning("Stack %s not deployed yet; skipping", stack_name)
            return None
        for resource in resources:
            if (
                resource["ResourceType"]
                == "AWS::AutoScaling::AutoScalingGroup"
            ):
                return resource["PhysicalResourceId"]
        mlog.warning(
            "No AWS::AutoScaling::AutoScalingGroup found in stack %s; "
            "skipping",
            stack_name,
        )
        return None

    def run(self, direction: str) -> None:
        """Scale every discovered ASG "up" (to config min/max) or "down" (to 0)."""
        for stack_id in self.stack_ids():
            s_input = SimpleAsgInput.from_config_directory(
                self.data_path, stack_id, env_setting=self.env_setting
            )
            asg_name = self._asg_name(f"{s_input.prefix()}Stack")
            if asg_name is None:
                continue

            if direction == "down":
                min_size = max_size = desired = 0
            else:
                min_size = s_input.sa_setting.min_instances
                max_size = s_input.sa_setting.max_instances
                desired = min_size

            mlog.info(
                "%s (%s): min=%d max=%d desired=%d",
                stack_id,
                asg_name,
                min_size,
                max_size,
                desired,
            )
            self.autoscaling.update_auto_scaling_group(
                AutoScalingGroupName=asg_name,
                MinSize=min_size,
                MaxSize=max_size,
                DesiredCapacity=desired,
            )


def get_args() -> argparse.Namespace:
    """Parse direction ("up"/"down") and environment from CLI args."""
    parser = argparse.ArgumentParser(
        description="Scale simple_asg Auto Scaling Groups up or down."
    )
    parser.add_argument("direction", choices=["up", "down"])
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    return parser.parse_args()


def main() -> None:
    """Scale the requested environment's Auto Scaling Groups."""
    args = get_args()
    AsgScaler(args.environment).run(args.direction)


if __name__ == "__main__":
    main()
