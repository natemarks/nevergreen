# SecureS3Stack

A reusable CDK multi-stack for deploying HIPAA-grade S3 buckets. Encapsulates the
controls described in [`specs/s3-hipaa-security.md`](../specs/s3-hipaa-security.md).
Add one line to `STACKS_BY_ENV` and a JSON config file to deploy a fully secured bucket.

---

## What this stack deploys

- **CMK** — a customer-managed KMS key scoped to this bucket, with configurable rotation
- **Primary bucket** — DSSE-KMS encrypted, versioned, with enforced bucket policy layers
- **Bucket policies** — HTTPS-only, DSSE encryption enforcement, VPC endpoint restriction
- **Read policy** — IAM managed policy for read-only application access
- **Read-write policy** — IAM managed policy for read/write application access
- **SSM parameter** — CMK ARN stored at `/{app_name}/{env}/secure_s3/{stack_id}/cmk-arn`
- **CloudFormation outputs** — ARNs for all key resources

Optional (controlled by config):
- **Companion logging bucket** — receives S3 server access logs
- **Object Lock / WORM** — GOVERNANCE or COMPLIANCE mode with configurable retention
- **Lifecycle expiration rule** — automatically deletes objects after N days

---

## Adding a new instance

1. Create a config file at `config/<env>/secure_s3/<stack_id>/secure_s3.json`.
2. Add `secure_s3("<stack_id>")` to the appropriate environment list in
   `config/registry.py`, after `app_vpc` (the VPC must deploy first).
3. Run `make discover app_env=<env>` (no-op for this stack — no discovery needed).
4. Run `make cdk-diff-all app_env=<env>` to review the planned changes.

Example registry entry:

```python
STACKS_BY_ENV = {
    "dev": [app_vpc, simple_asg("aaa"), secure_s3("patient-records")],
}
```

---

## Configuration field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `rotation_period_days` | int | 180 | KMS key rotation period (90–2560 days) |
| `enable_access_logging_bucket` | bool | false | Deploy a companion logging bucket |
| `worm_enabled` | bool | false | Enable S3 Object Lock at bucket creation |
| `worm_mode` | string | "GOVERNANCE" | `"GOVERNANCE"` or `"COMPLIANCE"` |
| `worm_retention_days` | int | 2555 | Object Lock retention period in days |
| `enable_lifecycle_expiration` | bool | false | Enable lifecycle expiration rule |
| `deletion_days` | int | 1095 | Days before objects expire |
| `removal_policy` | string | "DESTROY" | `"DESTROY"` or `"RETAIN"` for `cdk destroy` |

---

## Preflight validation

The settings dataclass checks for incompatible configurations at synthesis time.
If any check fails, a `ValueError` is raised before any CloudFormation is generated.

| Rule | Error |
|---|---|
| `worm_mode` not in `{"GOVERNANCE","COMPLIANCE"}` | Invalid value message |
| `removal_policy` not in `{"DESTROY","RETAIN"}` | Invalid value message |
| `rotation_period_days` outside 90–2560 | Out-of-range message |
| `worm_enabled=true` and `worm_retention_days < 1` | Invalid retention message |
| `enable_lifecycle_expiration=true` and `deletion_days < 1` | Invalid days message |
| `enable_lifecycle_expiration=true` and `worm_enabled=true` and `deletion_days <= worm_retention_days` | Conflict message with fix instructions |

**Lifecycle + WORM conflict example:**

```
ValueError: enable_lifecycle_expiration=True with deletion_days=365 conflicts with
worm_enabled=True and worm_retention_days=2555. The lifecycle rule cannot delete
WORM-locked objects before their retention period expires. Fix: either set
enable_lifecycle_expiration=False, set deletion_days > worm_retention_days, or
set worm_enabled=False.
```

---

## Attaching access policies to an application role

Both `read_policy` and `read_write_policy` are properties on `SecureS3Stack`.
Retrieve the deployed stack via `_get_deployed` in inventory and attach the policy
to any IAM role:

```python
# In a downstream stack constructor
phi_stack = cast(SecureS3Stack, inv._get_deployed("NevergreenvDevSecureS3PhiStack"))

my_role.add_managed_policy(phi_stack.read_policy)        # read-only
my_role.add_managed_policy(phi_stack.read_write_policy)  # read + write
```

The policies grant the minimum permissions required for S3 and KMS access scoped to
this specific bucket and CMK. Application code needs no KMS ARNs or bucket ARNs — the
bucket's default encryption handles key selection transparently.

---

## Test resource walkthrough

To verify a SecureS3 bucket is working, deploy a test EC2 instance or Lambda that has
the `read_write_policy` attached and attempt a PUT and GET.

**Example: test Lambda in the same stack or a sibling stack**

1. Create an IAM role for the Lambda with no other policies.
2. Attach `phi_stack.read_write_policy` to the role.
3. Deploy a Lambda function in a private VPC subnet with the S3 gateway endpoint in
   the route table (already present via `AppVpcStack`).
4. Invoke the Lambda with a test payload that calls `s3:PutObject` and `s3:GetObject`.
5. Verify the object is encrypted with DSSE-KMS by checking the object metadata in the
   S3 console or via `aws s3api head-object --bucket <name> --key <key>`.

A Lambda without the policy or outside the VPC will receive an `AccessDenied` error,
confirming the bucket policy restrictions are enforced.

---

## Stack outputs reference

| Output key | Value |
|---|---|
| `BucketArn` | Primary bucket ARN |
| `CmkArn` | Customer-managed KMS key ARN |
| `ReadPolicyArn` | Read-only managed policy ARN |
| `ReadWritePolicyArn` | Read-write managed policy ARN |
| `CmkArnSsmPath` | SSM parameter path for CMK ARN |
| `LoggingBucketArn` | Companion logging bucket ARN (only when `enable_access_logging_bucket=true`) |

---

## ⚠️ Production checklist

Two settings **must** be changed from their defaults before any PHI bucket goes live.
The default values are chosen for development ergonomics; they are not appropriate for
production.

### 1. Set `removal_policy` to `"RETAIN"`

```json
{ "removal_policy": "RETAIN" }
```

The default `"DESTROY"` allows `cdk destroy` to delete the bucket and all its contents.
In production, this must be `"RETAIN"` so that a mis-fired `cdk destroy` does not
permanently delete PHI.

### 2. Set `worm_mode` to `"COMPLIANCE"` (when WORM is enabled)

```json
{ "worm_enabled": true, "worm_mode": "COMPLIANCE" }
```

The default `"GOVERNANCE"` mode allows users with `s3:BypassGovernanceRetention` to
delete locked objects, which is useful for test iteration but defeats WORM protection
in production. `"COMPLIANCE"` mode is immutable — no principal, including account root,
can delete or shorten retention on locked objects before the retention period expires.

**Object Lock requires `worm_enabled=true` at bucket creation time.** It cannot be
added to an existing bucket. Changing `worm_enabled` from `false` to `true` on an
existing deployment triggers bucket replacement — all objects will be lost unless
migrated first.

---

## Emergency lockout

If a PHI breach is suspected, disable the CMK immediately:

```bash
aws kms disable-key --key-id <cmk-arn>
```

This makes all objects in the bucket unreadable instantly, for all principals, without
deleting any objects. Re-enable the key once the incident is resolved:

```bash
aws kms enable-key --key-id <cmk-arn>
```

The CMK ARN is available in the `CmkArn` CloudFormation output or the SSM parameter
at `/{app_name}/{env}/secure_s3/{stack_id}/cmk-arn`.
