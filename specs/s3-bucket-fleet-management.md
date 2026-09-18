# S3 Bucket Fleet Management: Engineer's Reference

This document consolidates official AWS guidance on discovering and managing a growing
fleet of `SecureS3Stack` instances across environments. Each instance creates a primary
PHI S3 bucket, a dedicated CMK, an optional access-logging bucket, and (planned) an
S3 Inventory destination and a dedicated CloudTrail trail. As the fleet grows,
operators need a queryable inventory. Every claim cites its source URL.

---

## Table of Contents

1. [Overview](#1-overview)
2. [AWS Config for Fleet Inventory](#2-aws-config-for-fleet-inventory)
   - 2.1 [Resource Types Tracked by Config](#21-resource-types-tracked-by-config)
   - 2.2 [Advanced Queries (Config SQL)](#22-advanced-queries-config-sql)
   - 2.3 [Multi-Account Aggregation](#23-multi-account-aggregation)
   - 2.4 [Limitations for Cross-Type Correlation](#24-limitations-for-cross-type-correlation)
3. [Resource Groups / Tag-Based Inventory](#3-resource-groups--tag-based-inventory)
   - 3.1 [Tag-Based Query Mechanics](#31-tag-based-query-mechanics)
   - 3.2 [Tags Currently Applied by This Repo](#32-tags-currently-applied-by-this-repo)
   - 3.3 [Adding a Stack-Instance Tag](#33-adding-a-stack-instance-tag)
   - 3.4 [AppRegistry and myApplications — Closed to New Customers](#34-appregistry-and-myapplications--closed-to-new-customers)
4. [SSM Parameter Store as a Registry](#4-ssm-parameter-store-as-a-registry)
   - 4.1 [Current State](#41-current-state)
   - 4.2 [Recommended Extension](#42-recommended-extension)
   - 4.3 [Operational Benefits](#43-operational-benefits)
5. [CloudFormation Stack Outputs as a Source of Truth](#5-cloudformation-stack-outputs-as-a-source-of-truth)
   - 5.1 [What the Outputs Provide](#51-what-the-outputs-provide)
   - 5.2 [Practical Limits at Fleet Scale](#52-practical-limits-at-fleet-scale)
6. [Recommended Pattern](#6-recommended-pattern)
   - 6.1 [Layered Strategy](#61-layered-strategy)
   - 6.2 [HIPAA Auditor Evidence Package](#62-hipaa-auditor-evidence-package)
7. [Implementation Checklist](#7-implementation-checklist)

---

## 1. Overview

A mature `SecureS3Stack` fleet spans three concerns:

| Concern | Question | Best tool |
|---|---|---|
| Operational lookup | "What is the CMK ARN for the `claims` bucket in prod?" | SSM Parameter Store (path query) |
| Compliance inventory | "List every PHI S3 bucket and its encryption key." | AWS Config advanced query |
| Ad-hoc / console discovery | "Show me all resources belonging to a specific stack instance." | Resource Groups tag-based query |
| Per-instance authoritative data | "What did CDK actually deploy for stack `claims`?" | CloudFormation stack outputs |

None of these tools is sufficient alone. Sections 2–5 describe each mechanism in
detail; Section 6 gives the recommended combination.

---

## 2. AWS Config for Fleet Inventory

### 2.1 Resource Types Tracked by Config

AWS Config records configuration items (CIs) for all resource types relevant to a
`SecureS3Stack` instance. The resource type identifiers and recorded attributes are:

**Amazon S3**

| Resource Type | What Config Records |
|---|---|
| `AWS::S3::Bucket` | Bucket name, ARN, encryption configuration, versioning state, logging configuration (target bucket + prefix), lifecycle rules, bucket policy (stored within the bucket CI), object lock configuration, tags |
| `AWS::S3::BucketPolicy` | Policy document is stored within the associated `AWS::S3::Bucket` CI, not as a separate queryable item |
| `AWS::S3::AccountPublicAccessBlock` | Account-level Block Public Access settings |

Source: https://docs.aws.amazon.com/config/latest/developerguide/resource-config-reference.html

**AWS KMS**

| Resource Type | What Config Records |
|---|---|
| `AWS::KMS::Key` | Key ARN, key ID, key policy, enabled/disabled state, rotation enabled flag, key manager (`CUSTOMER` vs `AWS`), key usage, tags |
| `AWS::KMS::Alias` | Alias name and target key ARN |

Source: https://docs.aws.amazon.com/config/latest/developerguide/resource-config-reference.html

**AWS CloudTrail**

| Resource Type | What Config Records |
|---|---|
| `AWS::CloudTrail::Trail` | Trail ARN, destination S3 bucket, encryption key ARN, multi-region flag, log file validation flag, data event selectors |
| `AWS::CloudTrail::EventDataStore` | Event data store ARN, retention period, encryption key |

Source: https://docs.aws.amazon.com/config/latest/developerguide/resource-config-reference.html

### 2.2 Advanced Queries (Config SQL)

AWS Config Advanced Query uses a subset of SQL `SELECT` syntax to query the current
state of configuration items without calling individual service APIs.

**Syntax:**

```sql
SELECT property [, ...]
[ WHERE condition ]
[ GROUP BY property ]
[ ORDER BY property [ ASC | DESC ] ]
```

**Example: List all S3 buckets in a specific environment**

```sql
SELECT resourceId, arn, configuration.location.name
WHERE resourceType = 'AWS::S3::Bucket'
AND tags.key = 'app_env'
AND tags.value = 'prod'
```

**Example: List all customer-managed KMS keys tagged for this app**

```sql
SELECT resourceId, arn
WHERE resourceType = 'AWS::KMS::Key'
AND configuration.keyManager = 'CUSTOMER'
AND tags.key = 'app_env'
AND tags.value = 'prod'
```

**Example: Count PHI buckets by environment**

```sql
SELECT tags.value, COUNT(*)
WHERE resourceType = 'AWS::S3::Bucket'
AND tags.key = 'app_env'
GROUP BY tags.value
```

APIs: `SelectResourceConfig` (single account) and `SelectAggregateResourceConfig`
(multi-account via aggregator).

Source: https://docs.aws.amazon.com/config/latest/developerguide/querying-AWS-resources.html
Source: https://docs.aws.amazon.com/config/latest/developerguide/query-components.html
Source: https://docs.aws.amazon.com/config/latest/APIReference/API_SelectAggregateResourceConfig.html

### 2.3 Multi-Account Aggregation

AWS Config supports a **configuration aggregator** that replicates CIs from source
accounts and regions into a designated aggregator account. Running
`SelectAggregateResourceConfig` against the aggregator executes the SQL query across
all aggregated accounts and regions in a single call.

Key properties of aggregation:
- **No additional cost** — aggregators do not incur extra Config charges.
- Read-only view: the aggregator cannot deploy rules or push changes to source accounts.
- Authorization: source accounts must grant the aggregator permission, or you can
  authorize via AWS Organizations (no per-account grant needed for org-wide aggregation).

This makes the aggregator the natural home for fleet-wide PHI inventory queries
across dev, staging, and production accounts.

Source: https://docs.aws.amazon.com/config/latest/developerguide/config-concepts.html

### 2.4 Limitations for Cross-Type Correlation

Config SQL has important limitations that affect fleet inventory:

- **No `JOIN` support.** You cannot write a single query that returns each S3 bucket
  alongside its CMK ARN by correlating `AWS::S3::Bucket` with `AWS::KMS::Key`. Each
  resource type must be queried separately and correlated offline or in application code.
- **No nested structure unpacking.** Tags are queryable (filter by key/value) but cannot
  be fully traversed within a SELECT.
- **No deleted resource queries.** Config SQL only reflects currently existing resources;
  deleted resources require the `LookupResources` API.
- **Resources not being recorded cannot be queried.** The configuration recorder must be
  enabled for each resource type. Update recorder settings to cover all four types.
- **No `NULL` value queries.** Missing or null properties cannot be tested directly.

Source: https://docs.aws.amazon.com/config/latest/developerguide/querying-AWS-resources.html

---

## 3. Resource Groups / Tag-Based Inventory

### 3.1 Tag-Based Query Mechanics

AWS Resource Groups supports **tag-based queries** (`TAG_FILTERS_1_0` type) that find
all resources in an account+region matching specified tag key/value pairs. The query
can target specific resource types or use `AWS::AllSupported` to match any resource
type.

Resource types relevant to a `SecureS3Stack` instance — `AWS::S3::Bucket`,
`AWS::KMS::Key`, and `AWS::CloudTrail::Trail` — are all supported by Resource Groups
tag-based queries.

**CLI example — create a group for all prod PHI resources:**

```bash
aws resource-groups create-group \
  --name "secure-s3-prod" \
  --resource-query '{
    "Type": "TAG_FILTERS_1_0",
    "Query": "{\"ResourceTypeFilters\":[\"AWS::AllSupported\"],\"TagFilters\":[{\"Key\":\"app_env\",\"Values\":[\"prod\"]}]}"
  }'
```

**CLI example — search without creating a persistent group:**

```bash
aws resource-groups search-resources \
  --resource-query '{
    "Type": "TAG_FILTERS_1_0",
    "Query": "{\"ResourceTypeFilters\":[\"AWS::S3::Bucket\",\"AWS::KMS::Key\"],\"TagFilters\":[{\"Key\":\"app_env\",\"Values\":[\"prod\"]}]}"
  }'
```

Source: https://docs.aws.amazon.com/ARG/latest/userguide/gettingstarted-query.html
Source: https://docs.aws.amazon.com/ARG/latest/userguide/gettingstarted-query-tag-based.html

### 3.2 Tags Currently Applied by This Repo

`Inventory.set_environment_tags` in `config/inventory.py` applies three tags to every
resource in the CDK app at synthesis time:

| Tag key | Value | Utility |
|---|---|---|
| `env_id` | `app_env` value (e.g., `prod`) | Fleet-level filter |
| `app_env` | `app_env` value (e.g., `prod`) | Fleet-level filter (duplicate for compatibility) |
| `Environment` | `app_env` value (e.g., `prod`) | Fleet-level filter |

These tags support a Resource Groups query that finds **all** resources across all
`SecureS3Stack` instances in a given environment. They do not support filtering to a
**specific** stack instance (e.g., "show me only the `claims` bucket and its CMK").

### 3.3 Adding a Stack-Instance Tag

To enable per-instance Resource Groups, apply a `stack_id` tag to all resources in
each `SecureS3Stack` at instantiation time:

```python
# In SecureS3Stack.__init__, after creating all resources:
from aws_cdk import Tags
Tags.of(self).add("secure_s3_id", s_input.stack_id)
```

With this tag in place, a Resource Groups query filtering on both `app_env=prod` and
`secure_s3_id=claims` returns exactly the S3 bucket, CMK, logging bucket, IAM policies,
and CloudTrail trail that belong to the `claims` instance in production.

For fleet-wide inventory, filter on `app_env=prod` only (without `secure_s3_id`)
to retrieve every resource across all instances in that environment.

**Tag naming note:** Resource Groups tag filters are exact-match on key and value
strings. The tag key must be applied consistently to all resource types in the stack
— CDK `Tags.of(self).add(...)` propagates tags to all constructs in the scope, which
is the correct approach.

Source: https://docs.aws.amazon.com/ARG/latest/userguide/gettingstarted-query.html

### 3.4 AppRegistry and myApplications — Closed to New Customers

Two AWS application grouping services were previously the recommended path for this
use case:

- **AWS Service Catalog AppRegistry**: "No longer open to new customers. Existing
  customers can continue to use the service as normal."
- **myApplications** (AWS Console Home): "myApplications no longer allows creation of
  new applications. For resource grouping capabilities, explore AWS Resource Groups."

AWS now directs new workloads to **AWS Resource Groups** for resource grouping.
Do not build new automation around AppRegistry or myApplications.

Source (AppRegistry closure): https://docs.aws.amazon.com/servicecatalog/latest/arguide/overview-appreg.html
Source (myApplications closure): https://docs.aws.amazon.com/awsconsolehelpdocs/latest/gsg/aws-myApplications.html

---

## 4. SSM Parameter Store as a Registry

### 4.1 Current State

`SecureS3Stack` already stores the CMK ARN in SSM Parameter Store at:

```
/{app}/{env}/secure_s3/{stack_id}/cmk-arn   (type: String)
```

This path is published as the `CmkArnSsmPath` CloudFormation output. The parameter
stores the ARN as a plain `String` — not `SecureString` — because a CMK ARN is a
resource identifier, not a secret credential.

### 4.2 Recommended Extension

Store all primary resource ARNs under the same `/{app}/{env}/secure_s3/{stack_id}/`
path prefix. The complete parameter set per stack instance:

| SSM Parameter | Value | When created |
|---|---|---|
| `/{app}/{env}/secure_s3/{id}/cmk-arn` | CMK ARN | Always (existing) |
| `/{app}/{env}/secure_s3/{id}/bucket-arn` | Primary bucket ARN | Always (add now) |
| `/{app}/{env}/secure_s3/{id}/logging-bucket-arn` | Access-logging bucket ARN | When `enable_access_logging_bucket=true` |
| `/{app}/{env}/secure_s3/{id}/inventory-bucket-arn` | S3 Inventory destination bucket ARN | When inventory bucket is implemented |
| `/{app}/{env}/secure_s3/{id}/trail-arn` | Dedicated CloudTrail trail ARN | When per-stack trail is implemented |

All parameters are plain `String` type. ARNs are resource identifiers; they do not
require encryption at rest.

### 4.3 Operational Benefits

**Fleet-wide discovery with a single API call:**

```bash
# All ARNs for all instances in prod
aws ssm get-parameters-by-path \
  --path "/myapp/prod/secure_s3/" \
  --recursive

# All ARNs for the 'claims' instance in prod
aws ssm get-parameters-by-path \
  --path "/myapp/prod/secure_s3/claims/" \
  --recursive
```

`GetParametersByPath` with `--recursive` returns every parameter under the path prefix
in a single paginated call, making it the lowest-latency programmatic discovery method
for the full set of ARNs in a given environment.

Source: https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-hierarchies.html
Source: https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetParametersByPath.html

**Decoupled consumption:** Lambda functions, SSM Automation runbooks, and other
automation that need to access PHI buckets can look up the bucket ARN and CMK ARN at
runtime by constructing a well-known SSM path from `{app}`, `{env}`, and `{stack_id}`
— no hardcoded ARNs in code, no CloudFormation describe calls, no IAM permissions
to CloudFormation.

**IAM path-based least privilege:** IAM policies can scope access to a specific
environment or stack instance using the path prefix:

```json
{
  "Effect": "Allow",
  "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
  "Resource": "arn:aws:ssm:*:*:parameter/myapp/prod/secure_s3/*"
}
```

**Runbook integration:** AWS Systems Manager Automation runbooks can resolve
parameter values dynamically using `{{ssm:/path/to/param}}` syntax — no changes to
the runbook document when a new stack instance is added.

**Rotation stability:** Because KMS key rotation preserves the CMK ARN, the stored
`cmk-arn` parameter never goes stale. The same stability applies to bucket ARNs and
trail ARNs — these do not change after creation.

Source: https://docs.aws.amazon.com/solutions/latest/automated-security-response-on-aws/aws-systems-manager-parameter-store.html

---

## 5. CloudFormation Stack Outputs as a Source of Truth

### 5.1 What the Outputs Provide

`SecureS3Stack` emits the following CloudFormation outputs at deploy time:

| Output Key | Value |
|---|---|
| `BucketArn` | Primary PHI bucket ARN |
| `CmkArn` | CMK ARN |
| `ReadPolicyArn` | IAM managed policy ARN (read-only) |
| `ReadWritePolicyArn` | IAM managed policy ARN (read-write) |
| `CmkArnSsmPath` | SSM parameter path for the CMK ARN |
| `LoggingBucketArn` | Access-logging bucket ARN (conditional) |

These are retrievable per-stack:

```bash
aws cloudformation describe-stacks \
  --stack-name <stack-name> \
  --query 'Stacks[0].Outputs'
```

### 5.2 Practical Limits at Fleet Scale

CloudFormation outputs are well-suited for per-instance lookups but are a poor choice
for programmatic fleet-wide discovery:

**O(n) API calls required.** `ListStacks` returns only stack summaries — it does not
include outputs. To get outputs for n stack instances, you must call `DescribeStacks`
n times (once per stack name). There is no batch operation.

Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ListStacks.html

**Performance warning from AWS:** The CloudFormation documentation explicitly warns:
"If you don't pass a parameter to `StackName`, the API returns a response that
describes all resources in the account, which can impact performance."

Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeStacks.html

**Pagination overhead.** `DescribeStacks` paginates at 1 MB. Large outputs or many
stacks require `NextToken` handling.

**No cross-environment aggregation.** CloudFormation is per-account and per-region;
there is no equivalent of the Config aggregator for CloudFormation outputs.

**Appropriate uses:**
- Verifying a specific stack deployed the expected ARNs.
- Bootstrapping the SSM parameters above (the CDK stack itself already does this).
- CI/CD post-deploy validation steps.
- Human operators spot-checking a single stack.

Not appropriate for:
- Automated fleet-wide ARN enumeration.
- Auditor inventory reports covering all environments.
- Runtime ARN lookup by Lambda or other automation.

---

## 6. Recommended Pattern

### 6.1 Layered Strategy

Use all four mechanisms, each for its intended purpose:

**Layer 1 — SSM Parameter Store (primary operational registry)**

Extend the existing `/{app}/{env}/secure_s3/{stack_id}/cmk-arn` parameter to include
`bucket-arn`, `logging-bucket-arn`, `inventory-bucket-arn`, and `trail-arn` under the
same path prefix. This is the primary registry for all runtime and automation consumers.

This requires adding three `ssm.StringParameter` constructs to `SecureS3Stack` (one
for each conditional resource, guarded by the same `Optional` check used for the
existing logging bucket CfnOutput).

**Layer 2 — AWS Config advanced queries (compliance inventory)**

Enable Config recording for `AWS::S3::Bucket`, `AWS::KMS::Key`, and
`AWS::CloudTrail::Trail` in all environments. For multi-account deployments, create
an organization-level configuration aggregator. This enables a single SQL query to
enumerate all PHI data stores across every environment and account — the format
HIPAA auditors expect for a PHI data store inventory.

The HIPAA Config conformance pack (`operational-best-practices-for-hipaa_security`)
adds automated compliance checks on top of this inventory at no additional cost.

Source: https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html

**Layer 3 — Resource Groups tag-based query (console and ad-hoc discovery)**

Apply a `secure_s3_id` tag (value: `stack_id`) to each `SecureS3Stack` using
`Tags.of(self).add("secure_s3_id", s_input.stack_id)`. This, combined with the
existing `app_env` tag, enables:

- Per-instance resource group: `app_env=prod AND secure_s3_id=claims`
- Fleet-wide group: `app_env=prod` with resource type filter
  `AWS::S3::Bucket,AWS::KMS::Key,AWS::CloudTrail::Trail`

Resource Groups can be created from the console or CLI and are visible in the AWS
Console's resource browser without requiring Config or SSM access.

**Layer 4 — CloudFormation outputs (per-instance source of truth)**

Use CloudFormation outputs for individual stack verification during CI/CD and for
operator spot-checks. Do not use them for fleet-wide discovery or runtime ARN lookup.

### 6.2 HIPAA Auditor Evidence Package

For a HIPAA audit, the following artifacts satisfy the requirement to enumerate all
PHI data stores and demonstrate control effectiveness:

| Auditor requirement | Evidence source |
|---|---|
| List all PHI S3 buckets | AWS Config SQL query on `AWS::S3::Bucket` tagged `app_env=prod` across the org aggregator |
| List all encryption keys protecting PHI | AWS Config SQL query on `AWS::KMS::Key` tagged `app_env=prod` |
| Confirm every PHI bucket has DSSE-KMS encryption | AWS Config conformance pack rule `s3-bucket-server-side-encryption-enabled` + Security Hub S3.17 |
| Confirm CloudTrail data events are enabled | AWS Config conformance pack rule `cloud-trail-log-file-validation-enabled` |
| Locate specific PHI bucket's CMK for key policy review | SSM `GetParametersByPath` on `/{app}/{env}/secure_s3/{stack_id}/` |

---

## 7. Implementation Checklist

### SSM Parameter Store Extension

- [ ] Add `ssm.StringParameter` for `bucket-arn` to `SecureS3Stack` (always created).
- [ ] Add `ssm.StringParameter` for `logging-bucket-arn` inside the
  `if cfg.enable_access_logging_bucket:` block.
- [ ] When S3 Inventory bucket is implemented: add `ssm.StringParameter` for
  `inventory-bucket-arn`.
- [ ] When per-stack CloudTrail trail is implemented: add `ssm.StringParameter` for
  `trail-arn`.
- [ ] Add corresponding `CfnOutput` entries for each new SSM parameter path.
- [ ] IAM: scope runbook and Lambda roles to read `/{app}/{env}/secure_s3/*` only.

### Tags

- [ ] Add `Tags.of(self).add("secure_s3_id", s_input.stack_id)` to `SecureS3Stack`.
- [ ] Update golden files: `make unit-update_golden && make unit-test`.
- [ ] Verify tag propagation in the synthesized CloudFormation template for bucket,
  CMK, logging bucket, and IAM policies.

### AWS Config

- [ ] Enable Config recording for `AWS::S3::Bucket`, `AWS::KMS::Key`,
  `AWS::KMS::Alias`, and `AWS::CloudTrail::Trail` in all environments.
- [ ] Create a configuration aggregator to cover all environment accounts
  (or use organization-level aggregation if using AWS Organizations).
- [ ] Deploy the HIPAA Config conformance pack in each account:
  `operational-best-practices-for-hipaa_security`.
- [ ] Validate that Config can record S3 buckets (S3 bucket policy must grant
  Config the required permissions — see Config documentation).

### Resource Groups

- [ ] Create a persistent tag-based Resource Group per environment
  (e.g., `secure-s3-prod`) filtering on `app_env=prod` with
  `AWS::AllSupported` resource type filter.
- [ ] Optionally create per-instance groups for frequently-accessed instances.

### CloudFormation Outputs (no new action required)

- [ ] Existing outputs (`BucketArn`, `CmkArn`, `ReadPolicyArn`, `ReadWritePolicyArn`,
  `CmkArnSsmPath`, `LoggingBucketArn`) are already present. No changes needed.

---

*Sources used in this document:*

- https://docs.aws.amazon.com/config/latest/developerguide/resource-config-reference.html
- https://docs.aws.amazon.com/config/latest/developerguide/querying-AWS-resources.html
- https://docs.aws.amazon.com/config/latest/developerguide/query-components.html
- https://docs.aws.amazon.com/config/latest/developerguide/config-concepts.html
- https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html
- https://docs.aws.amazon.com/config/latest/APIReference/API_SelectAggregateResourceConfig.html
- https://docs.aws.amazon.com/ARG/latest/userguide/gettingstarted-query.html
- https://docs.aws.amazon.com/ARG/latest/userguide/gettingstarted-query-tag-based.html
- https://docs.aws.amazon.com/servicecatalog/latest/arguide/overview-appreg.html
- https://docs.aws.amazon.com/awsconsolehelpdocs/latest/gsg/aws-myApplications.html
- https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-hierarchies.html
- https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetParametersByPath.html
- https://docs.aws.amazon.com/solutions/latest/automated-security-response-on-aws/aws-systems-manager-parameter-store.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeStacks.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ListStacks.html
