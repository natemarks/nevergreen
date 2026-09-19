"""Simple auto scaling group stack and input models.

Purpose:
- Define a stack that can be deployed multiple times per environment.
- Launch EC2 instances in AppVpc private subnets via a launch template.

Flow:
- `SimpleAsgInput.from_config_directory` loads stack-specific settings.
- `SimpleAsgStack` consumes `AppVpcStack` for VPC/subnet context.

Customize:
- instance type, scaling bounds, and root volume settings
- user data script: `stack/simple_asg/<userdata_filename>` (per-instance,
  set via `SimpleAsgSetting.userdata_filename`, defaults to `userdata.sh`)
- AMI source strategy (`ami_id` discovery vs managed image lookup)
- instance role permissions and security group rules
- optional inbound access: `ingress_cidr`/`ingress_ports` on
  `SimpleAsgSetting` (default: no inbound rules at all, private subnet,
  no public IP; setting `ingress_cidr` also moves the instance to a
  public subnet with a public IP, since a security-group rule alone
  isn't reachable from the internet without one)
- optional extra IAM managed policies on the instance role: pass
  `managed_policies` to `SimpleAsgStack`
- optional extra files delivered onto the instance before the userdata
  script runs: pass `extra_files` (a `{remote_path: local_path_or_content}`
  map) to `SimpleAsgStack`. A `Path` value uploads that local file as a CDK
  asset and downloads it from S3 at boot, so a tested repo file (e.g. a
  worker script) is the single source of truth instead of being duplicated
  inline in a shell script -- and, unlike embedding it in userdata
  directly, isn't bounded by EC2's 16KB userdata size limit. A `str` value
  is written via a small inline heredoc instead (an S3 asset must be a
  real file on disk at synth time, which a value containing a CDK token
  resolved only at deploy time -- e.g. a queue URL -- cannot be).
"""

import shlex
from dataclasses import dataclass
from pathlib import Path
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_autoscaling as autoscaling,
)
from aws_cdk import Environment as cdk_environment
from aws_cdk.aws_s3_assets import Asset
from constructs import Construct
from config.helper import APP_NAME
from config.settings import EnvironmentSetting, SimpleAsgSetting
from stack.app_vpc import AppVpcStack


def _build_inline_file_commands(extra_files: dict[str, str]) -> str:
    """Return heredoc commands that write each small extra_files entry.

    Each value is written to its remote_path verbatim, so a caller can
    embed a CDK token (e.g. a queue URL) resolved at deploy time. Only
    for small content -- see the module docstring's `extra_files` entry
    for why larger, disk-based files use an S3 asset download instead.
    """
    blocks = []
    for remote_path, content in extra_files.items():
        remote_dir = shlex.quote(str(Path(remote_path).parent))
        blocks.append(
            f"mkdir -p {remote_dir}\n"
            f"cat > {shlex.quote(remote_path)} <<'EXTRA_FILE_EOF'\n"
            f"{content}\n"
            "EXTRA_FILE_EOF\n"
        )
    return "\n".join(blocks)


@dataclass(frozen=True, kw_only=True)
class SimpleAsgInput:
    """Typed input payload for one SimpleAsg stack instance."""

    stack_id: str
    env_setting: EnvironmentSetting
    sa_setting: SimpleAsgSetting

    def prefix(self) -> str:
        """Return the stack/resource prefix including stack instance id."""
        return (
            f"{APP_NAME}{self.env_setting.prefix()}"
            f"SimpleAsg{self.stack_id.capitalize()}"
        )

    @classmethod
    def from_config_directory(
        cls,
        data_path: Path,
        stack_id: str,
        env_setting: EnvironmentSetting | None = None,
    ) -> "SimpleAsgInput":
        """Build SimpleAsg input from `config/<env>/simple_asg/<id>/...`."""
        return cls(
            stack_id=stack_id,
            env_setting=env_setting
            or EnvironmentSetting.from_data_path(data_path),
            sa_setting=SimpleAsgSetting.from_data_path(data_path, stack_id),
        )


class SimpleAsgStack(Stack):
    """CDK stack that provisions a simple EC2 Auto Scaling Group.

    This stack depends on `AppVpcStack`. By default it deploys instances
    into private subnets with no public IP; it also enables IMDSv2 and
    supports SSM Session Manager access. If `SimpleAsgSetting.ingress_cidr`
    is set, the instance moves to a public subnet with a public IP, and the
    security group allows inbound access from that CIDR on
    `ingress_ports` — a plain security-group rule on a private-subnet
    instance would be unreachable from the internet regardless.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
        self,
        scope: Construct,
        cdk_env: cdk_environment,
        s_input: SimpleAsgInput,
        app_vpc_stack: AppVpcStack,
        managed_policies: list[iam.IManagedPolicy] | None = None,
        extra_files: dict[str, Path | str] | None = None,
        **kwargs,
    ):
        self.s_input = s_input
        prefix = s_input.prefix()
        super().__init__(
            scope=scope, id=f"{prefix}Stack", env=cdk_env, **kwargs
        )
        self.vpc = app_vpc_stack.vpc
        instance_sg = ec2.SecurityGroup(
            self,
            f"{prefix}SecurityGroup",
            vpc=self.vpc,
            allow_all_outbound=True,
        )
        ingress_cidr = self.s_input.sa_setting.ingress_cidr
        # A security-group rule alone can't be reached from the internet if
        # the instance has no public IP / sits in a private subnet — there
        # is no inbound route. So ingress_cidr also switches the instance to
        # a public subnet with a public IP; instances that don't set it stay
        # in the private subnet with no public IP, exactly as before.
        subnet_type = (
            ec2.SubnetType.PUBLIC
            if ingress_cidr
            else ec2.SubnetType.PRIVATE_WITH_EGRESS
        )
        if ingress_cidr:
            for port in self.s_input.sa_setting.ingress_ports:
                instance_sg.add_ingress_rule(
                    peer=ec2.Peer.ipv4(ingress_cidr),
                    connection=ec2.Port.tcp(port),
                    description=f"Allow {ingress_cidr} on tcp/{port}",
                )
        # role for ASG instances
        # this must exist in order to use ssm_session_permissions parameter
        self.asg_role = iam.Role(
            self,
            f"{prefix}ASGRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
        )
        for managed_policy in managed_policies or []:
            self.asg_role.add_managed_policy(managed_policy)
        default_region = self.s_input.env_setting.default_region
        ami_id = self.s_input.sa_setting.ami_id
        userdata_file = (Path(__file__).parent) / (
            f"simple_asg/{self.s_input.sa_setting.userdata_filename}"
        )
        user_data = ec2.UserData.for_linux()
        asset_files = {
            remote_path: local_path
            for remote_path, local_path in (extra_files or {}).items()
            if isinstance(local_path, Path)
        }
        inline_files = {
            remote_path: content
            for remote_path, content in (extra_files or {}).items()
            if isinstance(content, str)
        }
        for index, remote_path in enumerate(sorted(asset_files)):
            asset = Asset(
                self,
                f"{prefix}ExtraFile{index}",
                path=str(asset_files[remote_path]),
            )
            asset.grant_read(self.asg_role)
            user_data.add_s3_download_command(
                bucket=asset.bucket,
                bucket_key=asset.s3_object_key,
                local_file=remote_path,
            )
        user_data.add_commands(_build_inline_file_commands(inline_files))
        user_data.add_commands(userdata_file.read_text(encoding="utf-8"))
        l_tpl = ec2.LaunchTemplate(
            self,
            f"{prefix}LaunchTpl",
            associate_public_ip_address=bool(ingress_cidr),
            block_devices=[
                ec2.BlockDevice(
                    device_name=self.s_input.sa_setting.root_block_device_name,
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=self.s_input.sa_setting.root_block_device_size,
                    ),
                )
            ],
            instance_type=ec2.InstanceType(
                self.s_input.sa_setting.instance_type
            ),
            # this is an easy way to grab the latest ECS image
            # but I wanted to use the AMI ID as an example of discovery
            # machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            machine_image=ec2.GenericLinuxImage(
                {
                    default_region: ami_id,
                }
            ),
            http_put_response_hop_limit=1,  # default=1
            require_imdsv2=True,  # default=False
            security_group=instance_sg,
            user_data=user_data,
            role=self.asg_role,
        )
        autoscaling.AutoScalingGroup(
            self,
            f"{prefix}ASG",
            min_capacity=self.s_input.sa_setting.min_instances,
            max_capacity=self.s_input.sa_setting.max_instances,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=subnet_type),
            ssm_session_permissions=True,
            launch_template=l_tpl,
        )
