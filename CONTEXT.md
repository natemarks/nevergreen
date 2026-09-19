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

---

## SqsQueue context

### SqsQueueStack
A multi-stack CDK stack type that provisions one standard SQS queue plus its
dead-letter queue, and consumer (receive/delete)/producer (send) IAM managed
policies. One instance per logical job queue. Follows the factory pattern:
`sqs_queue("explore-a")`.

### explore-a queue
The `SqsQueueStack` instance (`stack_id="explore-a"`) that carries
Character-A image-generation jobs for the `explore_worker.py` worker to
consume. Physical queue name: `nevergreen-<app_env>-explore-a-queue`.

### Job (explore-a worker)
A queue message of the shape `{"seed_prompt": str, "batch_size": int,
"job_id": str (optional)}`. `job_id` is generated if absent, and becomes the
S3 prefix `explore/{job_id}/` that all of that job's generated images are
written under.

### Model content delivery
Two independent steps, decided in wayfinder ticket #32, applied to both
SD checkpoints and the Ollama LLM: `make sync_models` populates the
models bucket from each content's own origin (Hugging Face for
checkpoints, a local `ollama pull` for the Ollama model) -- runs entirely
locally, no gpu_worker uptime needed just to sync content. Every
gpu_worker instance boot then runs `aws s3 sync` from the bucket's
`checkpoints/` and `ollama/` prefixes into
`/opt/comfyui/models/checkpoints/` and
`/usr/share/ollama/.ollama/models/` respectively -- the bucket's own
listing is the source of truth for both, deliberately with no separate
manifest of "currently synced content" to drift out of sync with it. This
also means neither Hugging Face nor Ollama's own registry is a live
dependency at instance boot -- pulling the Ollama model live from its
registry at every boot was the original design, but live UAT hit a
boot-time failure pulling it that a manual pull moments later didn't
reproduce, so the bucket became the single source for both.

### config/model_manifest.json
The list of model content `make sync_models` syncs: `{"checkpoints":
[{"repo_id", "filename"}, ...], "ollama_models": [<model name>, ...]}`.
Adding a new checkpoint or Ollama model is a one-line JSON edit, not a
code change.

## SecureS3 context

### SecureS3Stack
A multi-stack CDK stack type that provisions one HIPAA-grade S3 bucket and its
supporting resources (CMK, access policies, optional companion logging bucket). One
instance per logical data store. Follows the factory pattern: `secure_s3("patient-records")`.

### Bucket name (SecureS3)
The physical S3 bucket name, derived as `{app_name}-{app_env}-{stack_id}`. Not a
separate config field — always computed from existing identifiers. The companion logging
bucket appends `-access-logs` to this name.

### CMK (Customer-Managed KMS Key)
A KMS symmetric key created within a `SecureS3Stack` instance and scoped exclusively
to that bucket. One CMK per stack instance. Used for DSSE-KMS encryption of all objects
and for governing which IAM principals can read or write PHI.

### DSSE-KMS (Dual-layer server-side encryption)
The S3 encryption mode that applies two independent AES-256 encryption layers to each
object, each backed by the instance CMK. Selected over SSE-KMS for maximum at-rest
protection and Security Hub S3.17 compliance.

### Companion logging bucket
An optional S3 bucket provisioned within the same `SecureS3Stack` instance that receives
S3 server access logs for the primary bucket. Named `{app_name}-{app_env}-{stack_id}-access-logs`.
Enabled by `enable_access_logging_bucket: bool = False` in stack settings. Not a
separate `SecureS3Stack` instance — it is an internal resource of the same stack.

### Object Lock (WORM)
An S3 bucket feature that prevents object deletion or overwrite for a configurable
retention period. Must be enabled at bucket creation time; cannot be added to an existing
bucket. Controlled by `worm_enabled: bool = False` in stack settings.

### Object Lock mode
The enforcement level of Object Lock when WORM is enabled.
- **GOVERNANCE** (`worm_mode = "GOVERNANCE"`, default): IAM principals with
  `s3:BypassGovernanceRetention` can delete locked objects. Suitable for dev/test
  environments where iteration is required.
- **COMPLIANCE** (`worm_mode = "COMPLIANCE"`): No principal — including account root —
  can delete or shorten retention on locked objects. Required for production PHI.

The default is GOVERNANCE to allow `cdk destroy` to succeed during development. Production
config files must explicitly set `"COMPLIANCE"`.

### Lifecycle expiration
An S3 lifecycle rule that automatically deletes all object versions after `deletion_days`
days. Disabled by default (`enable_lifecycle_expiration: bool = False`). Distinct from
CDK removal policy (see below). Conflicts with Object Lock when
`deletion_days <= worm_retention_days`; the settings `__post_init__` raises a `ValueError`
with a remediation message if this condition is detected.

### CDK removal policy
The `aws_cdk.RemovalPolicy` applied to the primary bucket (and companion logging bucket)
controlling what `cdk destroy` does to the resource. `DESTROY` removes the bucket;
`RETAIN` leaves it in place. Separate from lifecycle expiration. Config field:
`removal_policy: str = "DESTROY"`. Production config files should set `"RETAIN"`.

### SecureS3 read policy
A CDK `ManagedPolicy` created within a `SecureS3Stack` instance granting `s3:GetObject`,
`s3:ListBucket`, and `kms:Decrypt` on the instance's bucket and CMK. Intended for
consumers that only read PHI (analytics, reporting).

### SecureS3 read-write policy
A CDK `ManagedPolicy` created within a `SecureS3Stack` instance granting all actions in
the read policy plus `s3:PutObject`, `s3:DeleteObject`, and `kms:GenerateDataKey`.
Intended for application services that write or modify PHI.

### extra_files (SimpleAsg)

A `{remote_path: local_path_or_content}` map passed to `SimpleAsgStack`.
Each entry is written to the instance via a userdata heredoc before the
main userdata script runs. A `Path` value embeds a local repo file's exact
content (e.g. a tested worker script); a `str` value is embedded verbatim,
letting a caller include a CDK token resolved only at deploy time (e.g. a
queue URL). See `stack/simple_asg.py`'s `_build_user_data`.

### VPC S3 gateway endpoint
An AWS VPC gateway endpoint for S3 added to `AppVpcStack`. Routes S3 traffic within the
VPC without traversing the public internet. Enables the `aws:sourceVpce` condition in
`SecureS3Stack` bucket policies to restrict access to traffic originating from the VPC.
Free; added unconditionally to `AppVpcStack`.
