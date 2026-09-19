"""Tests for config.inventory."""

import json
from unittest.mock import patch

import pytest
from aws_cdk import App, Environment, Stack, assertions

from config.helper import APP_NAME
from config.inventory import Inventory

_DEV = f"{APP_NAME}Dev"
_STG = f"{APP_NAME}Staging"
_PRD = f"{APP_NAME}Production"

EXPECTED_STACK_NAMES = {
    "dev": {
        f"{_DEV}AppVpcStack",
        f"{_DEV}SecureS3PhiStack",
        f"{_DEV}SimpleS3ModelsStack",
        f"{_DEV}SimpleS3ImagesStack",
        f"{_DEV}SqsQueueExplore-aStack",
        f"{_DEV}EcrRepoWorkerStack",
        f"{_DEV}SimpleAsgComfyuiStack",
    },
    "staging": {
        f"{_STG}AppVpcStack",
        f"{_STG}SecureS3PhiStack",
    },
    "production": {
        f"{_PRD}AppVpcStack",
        f"{_PRD}SecureS3PhiStack",
    },
}


@pytest.mark.unit
@pytest.mark.parametrize(
    "app_env,expected",
    [
        pytest.param("dev", EXPECTED_STACK_NAMES["dev"], id="dev"),
        pytest.param("staging", EXPECTED_STACK_NAMES["staging"], id="staging"),
        pytest.param(
            "production",
            EXPECTED_STACK_NAMES["production"],
            id="production",
        ),
    ],
)
def test_deploy_stacks_creates_expected_stacks(app_env, expected):
    """deploy_stacks creates exactly the stacks listed in STACKS_BY_ENV."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory(app_env)

    app = App()
    inv.deploy_stacks(app, Environment())

    actual = {s.stack_name for s in app.node.children if isinstance(s, Stack)}
    assert actual == expected


@pytest.mark.unit
def test_gpu_worker_gets_images_queue_models_and_ecr_managed_policies():
    """The comfyui instance role gets the images, queue, models, and ECR
    pull policies (Phase 2 wires the ECR pull policy in addition to
    Phase 1's three)."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    inv.deploy_stacks(app, Environment())

    gpu_worker_stack = next(
        s
        for s in app.node.children
        if isinstance(s, Stack)
        and s.stack_name == f"{_DEV}SimpleAsgComfyuiStack"
    )
    template = assertions.Template.from_stack(gpu_worker_stack)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "ManagedPolicyArns": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                ]
            )
        },
    )


@pytest.mark.unit
def test_gpu_worker_userdata_embeds_refresh_script_and_env_file():
    """The real dev wiring (containerized, Phase 2) embeds refresh_worker.sh
    and the env file with the container image URI -- not explore_worker.py
    directly, since Phase 2's image bundles its own copy."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    inv.deploy_stacks(app, Environment())

    gpu_worker_stack = next(
        s
        for s in app.node.children
        if isinstance(s, Stack)
        and s.stack_name == f"{_DEV}SimpleAsgComfyuiStack"
    )
    template = assertions.Template.from_stack(gpu_worker_stack).to_json()
    launch_templates = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::EC2::LaunchTemplate"
    ]
    assert len(launch_templates) == 1
    user_data = launch_templates[0]["Properties"]["LaunchTemplateData"][
        "UserData"
    ]["Fn::Base64"]

    # Fn::Base64 nests the resolved parts as an Fn::Join when any embedded
    # value (the queue URL, the bucket name) is a cross-stack token rather
    # than a plain string.
    rendered = json.dumps(user_data)
    assert "/opt/comfyui/bin/refresh_worker.sh" in rendered
    assert "/opt/comfyui/explore_worker.py" not in rendered
    assert "/etc/default/explore-worker" in rendered
    assert "QUEUE_URL=" in rendered
    assert "OUTPUT_BUCKET=" in rendered
    assert "MODELS_BUCKET=" in rendered
    assert "AWS_REGION=" in rendered
    assert "CONTAINER_IMAGE_URI=" in rendered
    assert "aws s3 sync" in rendered
    assert "refresh-worker.timer" in rendered


@pytest.mark.unit
def test_gpu_worker_gets_sqs_backlog_target_tracking_scaling_policy():
    """The comfyui ASG gets a target-tracking policy on SQS
    backlog-per-instance (target 2), via the L1 CfnScalingPolicy since
    CDK's L2 scale_to_track_metric only accepts a single direct metric,
    not this metric-math expression."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    inv.deploy_stacks(app, Environment())

    gpu_worker_stack = next(
        s
        for s in app.node.children
        if isinstance(s, Stack)
        and s.stack_name == f"{_DEV}SimpleAsgComfyuiStack"
    )
    template = assertions.Template.from_stack(gpu_worker_stack)

    backlog_query = assertions.Match.object_like(
        {
            "Id": "backlog",
            "MetricStat": assertions.Match.object_like(
                {
                    "Metric": assertions.Match.object_like(
                        {
                            "MetricName": "ApproximateNumberOfMessagesVisible",
                            "Namespace": "AWS/SQS",
                        }
                    )
                }
            ),
        }
    )
    instances_query = assertions.Match.object_like(
        {
            "Id": "instances",
            "MetricStat": assertions.Match.object_like(
                {
                    "Metric": assertions.Match.object_like(
                        {
                            "MetricName": "GroupInServiceInstances",
                            "Namespace": "AWS/AutoScaling",
                        }
                    )
                }
            ),
        }
    )
    backlog_per_instance_query = assertions.Match.object_like(
        {
            "Id": "backlog_per_instance",
            "Expression": "IF(instances > 0, backlog / instances, backlog)",
            "ReturnData": True,
        }
    )
    metric_spec = assertions.Match.object_like(
        {
            "Metrics": assertions.Match.array_with(
                [backlog_query, instances_query, backlog_per_instance_query]
            )
        }
    )
    target_tracking = assertions.Match.object_like(
        {
            "TargetValue": 2,
            "CustomizedMetricSpecification": metric_spec,
        }
    )
    template.has_resource_properties(
        "AWS::AutoScaling::ScalingPolicy",
        {
            "PolicyType": "TargetTrackingScaling",
            "TargetTrackingConfiguration": target_tracking,
        },
    )
    # GroupInServiceInstances (used above) only gets published when group
    # metrics collection is enabled on the ASG.
    template.has_resource_properties(
        "AWS::AutoScaling::AutoScalingGroup",
        {
            "MetricsCollection": assertions.Match.array_with(
                [assertions.Match.object_like({"Granularity": "1Minute"})]
            )
        },
    )


@pytest.mark.unit
def test_gpu_worker_without_ecr_repo_stays_bare_ec2():
    """ecr_repo_stack_id=None (Phase 0/1's design) still delivers
    explore_worker.py directly and skips the ECR pull policy -- this path
    has no real config exercising it anymore now that dev's comfyui is
    containerized, so it needs its own direct coverage."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    av_stack = inv._deploy_app_vpc(  # pylint: disable=protected-access
        app, Environment()
    )
    inv._deployed[av_stack.stack_name] = (  # pylint: disable=protected-access
        av_stack
    )
    images_stack = inv._deploy_simple_s3(  # pylint: disable=protected-access
        app, Environment(), "images"
    )
    inv._deployed[  # pylint: disable=protected-access
        images_stack.stack_name
    ] = images_stack
    models_stack = inv._deploy_simple_s3(  # pylint: disable=protected-access
        app, Environment(), "models"
    )
    inv._deployed[  # pylint: disable=protected-access
        models_stack.stack_name
    ] = models_stack
    queue_stack = inv._deploy_sqs_queue(  # pylint: disable=protected-access
        app, Environment(), "explore-a"
    )
    inv._deployed[  # pylint: disable=protected-access
        queue_stack.stack_name
    ] = queue_stack

    gpu_worker_stack = (
        inv._deploy_gpu_worker(  # pylint: disable=protected-access
            app,
            Environment(),
            "comfyui",
            "images",
            "explore-a",
            "models",
            None,
        )
    )

    template = assertions.Template.from_stack(gpu_worker_stack).to_json()
    launch_templates = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::EC2::LaunchTemplate"
    ]
    user_data = launch_templates[0]["Properties"]["LaunchTemplateData"][
        "UserData"
    ]["Fn::Base64"]
    rendered = json.dumps(user_data)
    assert "/opt/comfyui/explore_worker.py" in rendered
    assert "/opt/comfyui/workflows/txt2img-example.json" in rendered
    assert "CONTAINER_IMAGE_URI=" not in rendered

    role_resources = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::IAM::Role"
    ]
    assert len(role_resources) == 1
    # 3 attached (images read-write, queue consumer, models read) plus the
    # AWS-managed AmazonSSMManagedInstanceCore that ssm_session_permissions
    # always adds.
    assert len(role_resources[0]["Properties"]["ManagedPolicyArns"]) == 4
