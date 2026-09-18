# CloudTrail Data Events for a HIPAA PHI S3 Bucket in an AWS Organizations / Control Tower Environment

This document answers five operational questions about enabling CloudTrail S3 object-level
data events for a HIPAA PHI bucket when the account is managed by AWS Control Tower. Every
claim cites its primary source URL.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Control Tower Org Trail: What It Covers by Default](#2-control-tower-org-trail-what-it-covers-by-default)
   - 2.1 [What the Org Trail Captures](#21-what-the-org-trail-captures)
   - 2.2 [Data Events Are Not Enabled by Default](#22-data-events-are-not-enabled-by-default)
   - 2.3 [AFT Option for Org-Wide Data Events](#23-aft-option-for-org-wide-data-events)
   - 2.4 [Recommendation: Dedicated Member-Account Trail](#24-recommendation-dedicated-member-account-trail)
3. [Advanced Event Selectors: Scoping to a Single Bucket](#3-advanced-event-selectors-scoping-to-a-single-bucket)
   - 3.1 [Why Advanced Selectors Are Required](#31-why-advanced-selectors-are-required)
   - 3.2 [Selector JSON — CLI Example](#32-selector-json--cli-example)
   - 3.3 [Filtering to Specific Event Names](#33-filtering-to-specific-event-names)
4. [CDK Configuration](#4-cdk-configuration)
   - 4.1 [Trail Constructor Options Relevant to PHI](#41-trail-constructor-options-relevant-to-phi)
   - 4.2 [Adding the S3 Event Selector](#42-adding-the-s3-event-selector)
   - 4.3 [Complete Python Example](#43-complete-python-example)
   - 4.4 [Per-Bucket Stack vs. Separate Stack](#44-per-bucket-stack-vs-separate-stack)
5. [Cost with Advanced Event Selectors](#5-cost-with-advanced-event-selectors)
6. [Log File Integrity Validation](#6-log-file-integrity-validation)
7. [Recommended Configuration Checklist](#7-recommended-configuration-checklist)

---

## 1. Overview

AWS Control Tower creates an organization-level CloudTrail trail that covers all member
accounts. That trail captures **management events** (bucket creation, policy changes, IAM
operations, etc.) but does **not** capture S3 object-level (data) events by default.

To meet HIPAA §164.312(b) audit-control requirements — specifically, to record who accessed
which PHI object and when — you must separately enable CloudTrail data events for the PHI
bucket. Advanced event selectors allow that logging to be scoped to a single bucket ARN,
so you pay only for events on the bucket that matters.

---

## 2. Control Tower Org Trail: What It Covers by Default

### 2.1 What the Org Trail Captures

When you set up a landing zone, AWS Control Tower creates an **organization-level
CloudTrail trail** in the management account. This trail uses CloudTrail's _trusted
access_ feature so that it automatically applies to every member account in the
organization. Log files are delivered to the **Log Archive account**.

> "AWS Control Tower sets up a new CloudTrail trail when you set up a landing zone. It is an
> organization-level trail, which means that it logs all events for the management account
> and all member accounts in the organization."

Source: https://docs.aws.amazon.com/controltower/latest/userguide/about-logging.html

### 2.2 Data Events Are Not Enabled by Default

The org trail covers **management events** only. S3 data events (GetObject, PutObject,
DeleteObject, etc.) are **not captured** by the default Control Tower org trail. This is
consistent with CloudTrail's own default behavior: data events must be explicitly opted
into on any trail or event data store.

> "By default, trails and event data stores do not log data events. Additional charges
> apply for data events."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html

### 2.3 AFT Option for Org-Wide Data Events

AWS Account Factory for Terraform (AFT) provides an optional feature flag
`aft_feature_cloudtrail_data_events`. When set to `true`, AFT:

- Creates a separate Organization Trail in the management account.
- Enables S3 **and** Lambda data events for **all buckets in the entire organization**.
- Exports all data events (KMS-encrypted) to an `aws-aft-logs-*` bucket in the Log
  Archive account with log file validation enabled.

This is an org-wide blast: it affects every account whether managed by AFT or not, and
logs data events for every S3 bucket. The Log Archive account buckets are automatically
excluded to avoid recursive logging.

> "This setting works at the organization level. Enabling this setting affects all accounts
> in AWS Organizations, whether they are managed by AFT or not."

Source: https://docs.aws.amazon.com/controltower/latest/userguide/aft-feature-options.html

**Assessment for PHI:** Enabling the AFT flag is appropriate only if you want org-wide
coverage. For a single PHI bucket in a member account, a dedicated trail with advanced
event selectors is lower cost and simpler to reason about.

### 2.4 Recommendation: Dedicated Member-Account Trail

Create a **dedicated CloudTrail trail in the member account** scoped to the PHI bucket
using advanced event selectors. Advantages:

- Costs are proportional to the PHI bucket's activity, not org-wide S3 volume.
- The trail lifecycle, retention policy, and KMS key stay co-located with the bucket.
- Management events are intentionally excluded (the org trail already captures them);
  only data events are logged, so no duplicate management event charges arise.
- The trail can be created in the same CDK stack as the bucket.

Per CloudTrail's cost documentation, if an org trail already captures management events
in a Region, a second trail that _also_ captures management events in that Region incurs
a duplicate charge. A dedicated data-events-only trail does not trigger this because it
logs data events rather than a second copy of management events.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html

---

## 3. Advanced Event Selectors: Scoping to a Single Bucket

### 3.1 Why Advanced Selectors Are Required

Basic event selectors allow you to enable data events for either _all_ S3 buckets or a
specific bucket, but they offer no filtering by event name, identity, or prefix beyond a
single object prefix. **Advanced event selectors** are the correct tool when you need:

- A `StartsWith` match on `resources.ARN` to capture all objects in a specific bucket
  without enabling events on every other bucket.
- Optional filtering by `eventName` (e.g., only GetObject/PutObject/DeleteObject).
- Optional filtering by `readOnly` to separate read and write events.

Advanced event selectors use `resources.type = AWS::S3::Object` (not `AWS::S3::Bucket`)
for object-level events. Because S3 Object ARNs include the object key
(e.g., `arn:aws:s3:::my-bucket/path/to/object`), you must use `StartsWith` with the
bucket ARN followed by `/` — an exact `Equals` match would only capture a single specific
object path.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html
(section: "Log all Amazon S3 events for an Amazon S3 bucket by using advanced event selectors")

### 3.2 Selector JSON — CLI Example

The following CLI example configures a trail to log **all data events** (read and write)
for every object in `your-phi-bucket`:

```bash
aws cloudtrail put-event-selectors \
  --trail-name PhiBucketDataEventsTrail \
  --region us-east-1 \
  --advanced-event-selectors \
'[
  {
    "Name": "PHI-bucket-all-S3-data-events",
    "FieldSelectors": [
      { "Field": "eventCategory", "Equals": ["Data"] },
      { "Field": "resources.type",  "Equals": ["AWS::S3::Object"] },
      { "Field": "resources.ARN",   "StartsWith": ["arn:aws:s3:::your-phi-bucket/"] }
    ]
  }
]'
```

Note the trailing `/` in the bucket ARN value — CloudTrail's `StartsWith` match against
`arn:aws:s3:::your-phi-bucket/` captures all object keys inside that bucket.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html

### 3.3 Filtering to Specific Event Names

To restrict to only the three PHI-relevant operations (GetObject, PutObject, DeleteObject)
rather than all S3 data events, add an `eventName` condition:

```json
{
  "Name": "PHI-bucket-key-S3-events",
  "FieldSelectors": [
    { "Field": "eventCategory", "Equals": ["Data"] },
    { "Field": "resources.type",  "Equals": ["AWS::S3::Object"] },
    { "Field": "resources.ARN",   "StartsWith": ["arn:aws:s3:::your-phi-bucket/"] },
    { "Field": "eventName",       "Equals": ["GetObject", "PutObject", "DeleteObject"] }
  ]
}
```

CloudTrail also records `HeadObject`, `CopyObject`, `CreateMultipartUpload`, and
`CompleteMultipartUpload` as data events. For a HIPAA audit trail, capturing all object
operations (not just the three named above) is generally preferable — but narrowing to the
three core PHI-access events is valid if cost or volume justifies it.

Sources:
- Advanced event selector field reference: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/filtering-data-events.html
- S3 data events logged: https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging-s3-info.html

---

## 4. CDK Configuration

### 4.1 Trail Constructor Options Relevant to PHI

The `aws_cloudtrail.Trail` L2 construct accepts `TrailProps`. The key properties for a PHI
audit trail:

| Property | Recommended value | Purpose |
|---|---|---|
| `enable_file_validation` | `True` | SHA-256 + RSA digest files for tamper detection |
| `encryption_key` | A CMK `IKey` reference | Encrypts log files at rest in the destination bucket |
| `send_to_cloud_watch_logs` | `True` (optional) | Enables near-real-time CloudWatch Logs delivery for alerting |
| `is_multi_region_trail` | `True` | Captures S3 events regardless of which Region the API call originates from |
| `management_events` | `ReadWriteType.NONE` | Suppresses management events — the org trail already captures them |
| `is_organization_trail` | `False` (default) | This is a member-account scoped trail |

`TrailProps` signature (Python):

```python
from aws_cdk import aws_cloudtrail

aws_cloudtrail.TrailProps(
    bucket=None,                       # defaults to a new auto-created bucket
    enable_file_validation=None,       # bool
    encryption_key=None,               # IKey
    send_to_cloud_watch_logs=None,     # bool
    management_events=None,            # ReadWriteType
    is_multi_region_trail=None,        # bool
    is_organization_trail=None,        # bool
    ...
)
```

Source: https://constructs.dev/packages/aws-cdk-lib/v/2.268.0/api/TrailProps?lang=python&submodule=aws_cloudtrail

### 4.2 Adding the S3 Event Selector

The `Trail` construct exposes `add_s3_event_selector()` to scope data events to one or
more buckets:

```python
def add_s3_event_selector(
    s3_selector: list[S3EventSelector],
    exclude_management_event_sources: list[ManagementEventSources] = None,
    include_management_events: bool = None,
    read_write_type: ReadWriteType = None,
) -> None
```

`S3EventSelector` takes a `bucket` (an `IBucket`) and an optional `object_prefix`. Passing
no `object_prefix` (or an empty string) captures all objects in the bucket.

`ReadWriteType` options:
- `ReadWriteType.ALL` — both read (GetObject) and write (PutObject, DeleteObject) events.
- `ReadWriteType.READ_ONLY` — read events only.
- `ReadWriteType.WRITE_ONLY` — write events only.

For HIPAA: use `ReadWriteType.ALL` so that reads of PHI (GetObject) are also audited.

Source: https://constructs.dev/packages/aws-cdk-lib/v/2.268.0/api/Trail?lang=python&submodule=aws_cloudtrail

### 4.3 Complete Python Example

```python
import aws_cdk as cdk
from aws_cdk import (
    aws_cloudtrail as cloudtrail,
    aws_kms as kms,
    aws_s3 as s3,
)
from constructs import Construct


class PhiBucketStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- PHI bucket (encryption, versioning, etc. configured elsewhere) ---
        phi_bucket = s3.Bucket(
            self,
            "PhiBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # --- KMS key for encrypting the trail's own log files ---
        trail_key = kms.Key(
            self,
            "PhiTrailKey",
            enable_key_rotation=True,
            description="Encrypts CloudTrail data-event logs for PHI bucket",
        )

        # --- Dedicated data-events-only trail ---
        phi_trail = cloudtrail.Trail(
            self,
            "PhiBucketDataEventsTrail",
            # Log file integrity: SHA-256 + RSA digest chain
            enable_file_validation=True,
            # Encrypt log files with a CMK
            encryption_key=trail_key,
            # Multi-region so all API call origins are captured
            is_multi_region_trail=True,
            # Suppress management events — the org trail already captures them.
            # Avoids duplicate management-event charges.
            management_events=cloudtrail.ReadWriteType.NONE,
            # Optional: stream to CloudWatch Logs for real-time alerting
            send_to_cloud_watch_logs=True,
        )

        # Scope data events to this single PHI bucket, all object operations
        phi_trail.add_s3_event_selector(
            s3_selector=[
                cloudtrail.S3EventSelector(
                    bucket=phi_bucket,
                    object_prefix="",   # empty prefix = entire bucket
                )
            ],
            read_write_type=cloudtrail.ReadWriteType.ALL,
        )
```

**Under the hood:** `add_s3_event_selector()` synthesizes a CloudFormation
`AWS::CloudTrail::Trail` resource with `AdvancedEventSelectors` containing
`resources.type = AWS::S3::Object` and `resources.ARN StartsWith
arn:aws:s3:::your-bucket/`. The L2 construct handles the trailing-slash ARN format
automatically.

Sources:
- CDK Trail README (Python): https://constructs.dev/packages/aws-cdk-lib/v/2.268.0?submodule=aws_cloudtrail&lang=python
- AddEventSelectorOptions: https://constructs.dev/packages/aws-cdk-lib/v/2.268.0/api/AddEventSelectorOptions?lang=python&submodule=aws_cloudtrail

### 4.4 Per-Bucket Stack vs. Separate Stack

**Recommendation: include the trail in the per-bucket CDK stack.**

Arguments for co-location:
- The trail is meaningless without the bucket; they share the same lifecycle.
- The CDK `add_s3_event_selector()` call requires a reference to the `IBucket` object,
  which is cleanest when both are in the same stack.
- The trail's KMS key and CloudWatch log group belong to the same workload context.
- Discovery output (`config/<env>/`) for the bucket stack can record both the bucket ARN
  and the trail ARN together.

Arguments for a separate stack:
- If you have many PHI buckets and want a single trail with multiple event selectors,
  a single trail stack prevents trail proliferation and simplifies log aggregation.
- Org-level or account-level trails cannot be expressed as per-bucket CDK resources.

For this project's pattern (one `SecureS3Stack` per PHI bucket), the per-bucket approach
is simpler and keeps each stack self-contained.

---

## 5. Cost with Advanced Event Selectors

**S3 data events are charged for every delivery, including the first.** Unlike management
events (where the first copy per Region is free), data events have no free tier.

> "For data events, all deliveries incur CloudTrail costs, including the first."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html

**Current pricing (us-east-1):** $0.10 per 100,000 data events.

Source: https://aws.amazon.com/cloudtrail/pricing/

**Does scoping to a single bucket reduce cost?** Yes, proportionally. Advanced event
selectors instruct CloudTrail to evaluate and record only events that match the selector
conditions before they are delivered. An event on a bucket that does not match the
`resources.ARN StartsWith` condition is discarded — it is never delivered to your S3
bucket and you are not charged for it.

The $0.10/100K rate applies to the events actually delivered (those matching the selector),
not to the total volume of S3 events across the account. Scoping to a single PHI bucket
rather than all S3 buckets in the account will reduce costs by a factor proportional to
what share of total S3 activity the PHI bucket represents.

> "You can use advanced event selectors to include or exclude data events, giving you the
> ability to log only the data events of interest."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html

**Practical note on the org trail and duplicate events:** If the AFT `aft_feature_cloudtrail_data_events`
flag is also enabled, a member-account dedicated trail would produce a second copy of the
same data events. Each copy is billed separately. Keep only one of the two approaches
active per bucket to avoid duplicate data-event charges.

---

## 6. Log File Integrity Validation

### How it works

When `enable_file_validation=True` (CloudFormation: `EnableLogFileValidation: true`),
CloudTrail uses industry-standard cryptographic algorithms to guarantee that delivered log
files have not been modified, deleted, or forged:

- **SHA-256** — CloudTrail computes a hash for every log file it delivers.
- **SHA-256 with RSA digital signing** — Every hour, CloudTrail creates a _digest file_
  that lists the log files delivered during the previous hour, their SHA-256 hashes, and
  the hash of the previous digest file. CloudTrail signs the digest file with the private
  key of a Region-specific RSA key pair.
- **Digest file chaining** — Each digest file contains the digital signature of the
  previous digest file, forming a cryptographic chain. Tampering with any log file or
  digest file breaks the chain.

Digest files are delivered to the same S3 bucket as log files but in a separate prefix,
allowing fine-grained S3 bucket policies that protect them independently.

> "This feature is built using industry standard algorithms: SHA-256 for hashing and
> SHA-256 with RSA for digital signing. This makes it computationally infeasible to modify,
> delete or forge CloudTrail log files without detection."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html

### Does validation apply to data events?

Yes. Log file integrity validation applies to **all events** written to a trail's log
files — management events and data events alike. A single digest file covers every log
file delivered in the preceding hour regardless of event type. There is no distinction
in how digests are created for data vs. management event log files.

### Is this the right mechanism for HIPAA tamper detection?

Yes. The HIPAA Config conformance pack includes the rule `cloud-trail-log-file-validation-enabled`,
which maps to HIPAA Security Rule §164.308(a)(1)(ii)(B) (Risk Management). The rule fails
if log file validation is not enabled on any trail.

> "cloud-trail-log-file-validation-enabled — Log file validation must be on
> (SHA-256 + RSA integrity checking)"

Source: https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html

**Validating digests:** To confirm no log file has been tampered with, run:

```bash
aws cloudtrail validate-logs \
  --trail-arn arn:aws:cloudtrail:us-east-1:111122223333:trail/PhiBucketDataEventsTrail \
  --start-time 2026-01-01T00:00:00Z
```

The AWS CLI walks the digest chain and reports any missing or altered log file.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html

### Protecting the digest files themselves

Digest files are stored in the same S3 bucket as log files (separate prefix:
`AWSLogs/<account-id>/CloudTrail-Digest/`). Recommended protections:

- Apply S3 Object Lock (Compliance mode) with a retention period matching your HIPAA
  log retention policy (recommend 7 years) to prevent deletion.
- Use a separate bucket policy statement that denies `s3:DeleteObject` on the
  `CloudTrail-Digest/` prefix for all principals except the Log Archive account.
- Enable S3 MFA Delete as an additional safeguard.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html
(section: "Storing log and digest files")

---

## 7. Recommended Configuration Checklist

### Confirm org trail baseline

- [ ] Verify that the Control Tower org trail exists and is active in the Log Archive
  account (CloudTrail console → Trails → filter by org trail).
- [ ] Confirm the org trail is logging management events for the member account that
  holds the PHI bucket.
- [ ] Confirm the org trail does **not** already have data events enabled for all S3
  buckets (if it does, the dedicated trail below would produce duplicate data events
  billed separately).

### Create a dedicated data-events trail for the PHI bucket

- [ ] Trail scope: member account, multi-region.
- [ ] `enable_file_validation=True` (SHA-256 + RSA digest chain).
- [ ] `management_events=ReadWriteType.NONE` — suppress management events to avoid
  duplicate charges with the org trail.
- [ ] `encryption_key` — a dedicated CMK for trail log encryption. Not the same CMK as
  the PHI bucket data encryption key (separation of concerns).
- [ ] Trail's destination S3 bucket uses SSE-KMS (HIPAA conformance pack rule
  `cloud-trail-encryption-enabled`).
- [ ] `send_to_cloud_watch_logs=True` (optional but recommended for real-time alerting
  on unusual access patterns).

### Configure advanced event selectors

- [ ] `resources.type = AWS::S3::Object`
- [ ] `resources.ARN StartsWith arn:aws:s3:::your-phi-bucket/` (trailing slash required)
- [ ] `read_write_type=ReadWriteType.ALL` to capture both read (GetObject) and write
  (PutObject, DeleteObject) events.
- [ ] Optionally restrict `eventName` to `["GetObject", "PutObject", "DeleteObject"]`
  if volume warrants; otherwise leave open to capture multipart uploads and copies.

### Log retention

- [ ] Set an S3 Lifecycle policy on the trail's destination bucket to retain logs for at
  least 7 years (HHS guidance aligns with a 6-year HIPAA record retention minimum;
  7 years provides a buffer).
- [ ] Apply S3 Object Lock (Compliance mode) on the CloudTrail log and digest prefixes
  for tamper-evident immutability.

### Monitoring and detection

- [ ] CloudWatch Logs metric filter + alarm on `DeleteObject` volume anomalies (sudden
  mass deletion of PHI objects).
- [ ] CloudWatch Logs metric filter + alarm on `GetObject` volume anomalies (unexpected
  bulk reads that could indicate exfiltration).
- [ ] AWS Config rule `cloud-trail-log-file-validation-enabled` enabled in the member
  account (HIPAA conformance pack).

---

*Sources used in this document:*

- https://docs.aws.amazon.com/controltower/latest/userguide/about-logging.html
- https://docs.aws.amazon.com/controltower/latest/userguide/aft-feature-options.html
- https://docs.aws.amazon.com/controltower/latest/userguide/configure-org-trails.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/filtering-data-events.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html
- https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html
- https://aws.amazon.com/cloudtrail/pricing/
- https://constructs.dev/packages/aws-cdk-lib/v/2.268.0?submodule=aws_cloudtrail&lang=python
- https://constructs.dev/packages/aws-cdk-lib/v/2.268.0/api/TrailProps?lang=python&submodule=aws_cloudtrail
- https://constructs.dev/packages/aws-cdk-lib/v/2.268.0/api/AddEventSelectorOptions?lang=python&submodule=aws_cloudtrail
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging-s3-info.html
