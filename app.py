#!/usr/bin/env python3
"""CDK app entrypoint.

Purpose:
- Create the CDK app object and apply project/global tags.
- Resolve environment context (`app_env`) and load inventory settings.
- Deploy the environment's stack set using typed config data.

Flow:
- Read `app_env` from CDK context.
- Build inventory via `get_inventory(app_env)`.
- Build `cdk.Environment` from inventory settings.
- Call `deploy_stacks` and synthesize the app.

Customize:
- Add or change global tags in `config/template_defaults.json`.
- Change how `app_env` is resolved.
- Add pre-deploy validation gates before `deploy_stacks`.
"""

import aws_cdk as cdk
from config.project import IAC_PROJECT_URL
from config.inventory import get_inventory

# call the data sync checker to ensure the data is in sync

app = cdk.App()

# set hybrid env name from user input
app_env = app.node.try_get_context("app_env")

# set project-wide tag
cdk.Tags.of(app).add("iac", IAC_PROJECT_URL)

inv = get_inventory(app_env)
inv.set_environment_tags(app)

# set the cdk_environment
cdk_env = cdk.Environment(
    account=inv.environment_setting.aws_account_number,
    region=inv.environment_setting.default_region,
)

inv.deploy_stacks(app, cdk_env)


app.synth()
