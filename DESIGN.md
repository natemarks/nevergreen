# Design

The purpose oif this project is not to deploy and manage infrastructure as code. The purpose is to demonstrate some useful techniques for an AWS CDK (Python) project. 


## Project Maintenance

It's easy and useful to keep the project automation working. Please do.

### Automate Static checks with GNU make

These Makefile targets check for problems in the project. 

 - black: formats python files 
 - black-check fails if the formatting is bad. useful for protecting a repo in GH actions
 - pylint: pylint fails when it finds linting errors
 - shellcheck: fails when it find shell script problems
 - static: used locally to format python files, run checks and run unit tests. I run this often when I'm making changes
 - static-check: same as static, but with black-check.  used to check everything in GH actions to protect the repo

### Test Automation

These Makefile targets are uesd to run and maintain tests
 - unit-test: run the unit tests
 - unit-update_golden: run the unit tests. update golden files
 - aws-test: run tests that require aws credentials
 - aws-update_golden: run the aws tests and update golden files

### Update CDK Library

These Makefile targets help maintain CDK libraries required by the project

- update_cdk_libs: updates the requirements.txt file with the latest cdk library and deletes/recreates the python virtual environment with the updates.

## CDK Stacks

See the [README.md](./README.md) document to see how to deploy CDK stacks.


### Configuration Data

Configuration data is used to customize stacks in different environments
without chnaging the stack class. As an example, ASG scaling settings might be
used to keep  a dev ASG smaller than staging or produciton while using the same
stack class.

NOTE: configuration data must not be sensitive (credentials, keys, etc.).
Sensitive data should be in secretsmanager or similar


There is a config data directory for each environment.  Let's
look at the dev environment :

All dev environment the files are in config/dev/. The stack input classes use
this directory as a parameter.  All configuratiojn directories are organized in
the same way, so the input class can locate every individual file it needs by
just starting with the config directory path.  Each file has a corresponding
data class in config.settings

environment.json -> settings.EnvironmentSetting
app_vpc/app_vpc.json -> settings.AppVpcSetting
simple_asg/comfyui/simple_asg.json -> settings.SimpleAsgSetting

Dataclasses are used to make it easy to access/manage/update the data files.
Note that stacks that ccan be deployed many times in an environment have an
extra directory that matches the 'stack_id'. In this case,
simple_asg/comfyui/simple_asg.json contains the asg specific settings for the
ASG with the stack_id 'comfyui'. I can deploy many ASG stack so long as each
has a unique stack_id

To deploy a stack, I use the stack input class (ex. stack.app_vpc.AppVpcInput).
It requries the config directory path. Using that it gathers the required
EnvironmentSetting and AppVpcSetting needed to deploy
stack.app_vpc.AppVpcStack.

NOTE: The 'ACTUAL' environment data for dev, staging and production are in
config/, but this pattern of just passing around a root config directory also
makes it easy to create arbitrary, custom tets case input in test_data.

### Stack Deployment


All CDK projects use app.py as their entry point. For very small projects, you
can call the stack classes directly from here, but the more stacks your
platform requires, the bigger this file gets. Further, I often deploy different
stacks in each environment, so app.py would contain the additional complexity
of conditional logic to determine which stacks to deploy depending on the
environment 


I prefer to take that complexity out of app.py.  The app.py in this project
simply passes 'app_env' to get_inventory(), which returns an Inventory
instance. Inventory.deploy_stacks iterates STACKS_BY_ENV[app_env] — the
ordered list of StackFactory objects declared in config/registry.py — and
calls each factory's deploy callable in order.

STACKS_BY_ENV is the single place to answer "what stacks deploy in staging?"
and the single file to edit when adding a stack, adding an instance of an
existing stack type, or graduating a stack to a higher environment.

To see how the stack classes are used, look at config/registry.py and
inventory.py. Even better, look at the stack unit tests in tests/unit/stack/

### On-instance code delivery (extra_files)

Some stacks (`SimpleAsgStack`) need more than a shell script on the instance
-- e.g. a Python worker with its own test suite. Rather than hand-duplicating
that code inline in the userdata shell script, `SimpleAsgStack` accepts an
`extra_files` map of `{remote_path: local_path_or_content}`. A `Path` value
is read from disk and embedded verbatim via a heredoc, so the tested repo
file is the single source of truth for what runs on the instance. A `str`
value is embedded as-is, which lets a caller pass content built from a CDK
token only known at deploy time -- e.g. `Inventory._deploy_gpu_worker` builds
an `/etc/default/explore-worker` env file containing the real queue URL and
bucket name this way, resolved by CloudFormation at deploy time rather than
hardcoded at synth time. See `stack/simple_asg.py`'s `_build_user_data`.

