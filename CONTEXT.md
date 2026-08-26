# Domain Context

## Glossary

### Application environment (`app_env`)
A named deployment target such as `dev`, `staging`, or `production`. Maps to one AWS
account and one set of config files under `config/<app_env>/`.

### Config directory
The filesystem path `config/<app_env>/` that contains all JSON settings files for one
application environment. Passed to stack Input classes as their sole data source.

### Discovery
A function that fetches external AWS data (such as the latest ECS-optimised AMI ID) and
writes the result back to a config JSON file. Runs before CDK synthesis so the written
value is available when the stack Input class reads config. Not all stack types require
discovery.

### Eligible stack
A stack instance that appears in `cdk ls` for a given application environment — i.e., it
was added to the CDK `App` during `deploy_stacks`. Eligibility is declared in
`STACKS_BY_ENV`.

### Graduation
Promoting a stack from one environment's eligible set to a higher environment's eligible
set. Mechanically: adding the factory entry to the target environment's list in
`STACKS_BY_ENV` and adding the corresponding config files.

### Inventory
The object responsible for deploying all eligible stacks for one application environment.
Iterates `STACKS_BY_ENV[app_env]` and calls each factory's `deploy` function.

### Multi stack
A stack type deployed N times per environment, each with a distinct `stack_id` and its
own config directory at `config/<app_env>/<stack_type>/<stack_id>/`. Example:
`SimpleAsgStack` — one instance per ASG workload.

### Stack factory (`StackFactory`)
A dataclass that bundles the deploy callable and optional discover callable for one stack
instance. The eligibility list `STACKS_BY_ENV` is a list of `StackFactory` objects per
environment.

### Stack input (`*Input`)
A frozen dataclass that aggregates all settings objects required to synthesise one stack.
Loaded from the config directory via `from_config_directory`. Passed to the stack
constructor.

### Stack settings (`*Setting`)
A dataclass loaded from a single JSON file under the config directory. Represents one
category of configuration (e.g. `AppVpcSetting`, `SimpleAsgSetting`). Unique stacks have
one settings file; multi stacks have one per `stack_id`.

### Stack type
A CDK `Stack` subclass (e.g. `AppVpcStack`, `SimpleAsgStack`) — the Python class that
synthesises resources. Not the same as a stack instance.

### Unique stack
A stack type deployed at most once per environment. The eligibility list holds a single
`StackFactory` constant for it. Example: `AppVpcStack` — one VPC per environment.
