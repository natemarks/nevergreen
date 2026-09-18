# S3 Access Logging and Audit Log Integrity: Engineer's Reference

This document answers four design questions that arose while building the HIPAA PHI S3
bucket project. It focuses on CloudTrail data event costs, management event default
behavior, tamper protection for the server-access-log destination bucket, and the
completeness gap between S3 server access logging and CloudTrail. Every claim cites its
source URL.

---

## Table of Contents

1. [CloudTrail Data Events: Cost vs. S3 Server Access Logging](#1-cloudtrail-data-events-cost-vs-s3-server-access-logging)
2. [CloudTrail Management Events: Default Coverage in a New Account](#2-cloudtrail-management-events-default-coverage-in-a-new-account)
3. [Protecting the Server Access Log Destination Bucket](#3-protecting-the-server-access-log-destination-bucket)
   - 3.1 [The Object Lock Constraint](#31-the-object-lock-constraint)
   - 3.2 [Versioning](#32-versioning)
   - 3.3 [Lifecycle Rules and HIPAA 6-Year Retention](#33-lifecycle-rules-and-hipaa-6-year-retention)
   - 3.4 [Bucket Policy: Deny Deletion](#34-bucket-policy-deny-deletion)
   - 3.5 [True WORM for Server Access Logs](#35-true-worm-for-server-access-logs)
   - 3.6 [CDK Patterns](#36-cdk-patterns)
4. [S3 Server Access Logging Completeness vs. CloudTrail Data Events](#4-s3-server-access-logging-completeness-vs-cloudtrail-data-events)
5. [Practical Recommendations](#5-practical-recommendations)

---

## 1. CloudTrail Data Events: Cost vs. S3 Server Access Logging

### Pricing model

**CloudTrail data events (trail pricing):** Each copy of data events delivered to an S3
bucket is charged at **$0.10 per 100,000 events**. For data events, all trail deliveries
are charged, including the first. This is unlike management events, where the first copy
per Region is free.

> "For data events, all deliveries incur CloudTrail costs, including the first."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html

The authoritative price list is maintained at: https://aws.amazon.com/cloudtrail/pricing/

**S3 server access logging to an S3 bucket:** There is **no charge for log delivery**.
The only cost is S3 storage at standard rates. AWS explicitly states "There is no charge
for log delivery. You pay only for the storage of the log files."

**S3 server access logging to CloudWatch Logs:** Charged at CloudWatch vended logs
ingestion rates (volume-based tiered pricing). CloudWatch Logs compresses logs before
storage, so stored volume is significantly less than ingested volume.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html

### Cost comparison for high-throughput PHI buckets

| Logging mechanism | Per-event charge | Delivery SLA | Integrity validation |
|---|---|---|---|
| CloudTrail data events (trail) | $0.10 / 100k events | ~5 min | Yes (SHA-256 + RSA) |
| S3 server access logs → S3 bucket | None (storage only) | Best-effort, ~a few hours | No |
| S3 server access logs → CloudWatch Logs | CW vended logs rates | Best-effort, ~a few hours | No (CW log integrity) |

For a bucket with 10 million object operations per day (GetObject + PutObject), CloudTrail
data events cost approximately **$10/day or ~$300/month** at trail pricing, not including
S3 storage for the trail itself. At 100 million operations/day the cost is ~$3,000/month.
Server access logging for the same traffic has near-zero delivery cost.

### Assessment

S3 server access logging is dramatically cheaper than CloudTrail data events for
high-throughput buckets. However, cheapness alone does not make it adequate for HIPAA.
See section 4 for the completeness gaps that require CloudTrail for the primary
compliance record.

A practical strategy for high-throughput PHI buckets:
- Use CloudTrail data events scoped to **write and delete operations** only (PutObject,
  DeleteObject, CopyObject) — this records every mutation at a fraction of the full-event
  cost.
- Enable S3 server access logging for **read operations** (GetObject), HTTP-level details,
  and authentication failure capture.
- Use CloudTrail advanced event selectors to exclude read-only events from the trail if
  cost is the binding constraint, while documenting the decision as a risk acceptance.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html

---

## 2. CloudTrail Management Events: Default Coverage in a New Account

### Event History: always on, free, management events only

CloudTrail Event History is **active by default in every AWS account from the moment the
account is created**. No trail needs to be created. It provides a viewable, searchable,
downloadable, and immutable record of the **past 90 days** of management events in each
Region, at no charge.

> "CloudTrail is active in your AWS account when you create the account and you
> automatically have access to the CloudTrail Event history."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging.html

> "There are no CloudTrail charges for viewing the Event history page or running the
> lookup-events command."

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/how-cloudtrail-works.html

### What management events cover for S3

Management events are **control plane operations** — operations that configure or manage
resources. For S3, bucket-level operations are management events:

- `CreateBucket`, `DeleteBucket`
- `PutBucketPolicy`, `GetBucketPolicy`, `DeleteBucketPolicy`
- `PutBucketEncryption`, `PutBucketVersioning`, `PutBucketLogging`
- `PutBucketPublicAccessBlock`, `PutBucketObjectLockConfiguration`

All of these are captured by default in Event History in every new account.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-management-events-with-cloudtrail.html

### Limitations of Event History alone

| Limitation | Impact |
|---|---|
| 90-day rolling window | Logs older than 90 days are not visible unless a trail or event data store was created before that window |
| Management events only | Object-level access (GetObject, PutObject, DeleteObject) is not captured without a trail configured for data events |
| Single account, single Region per search | Cannot query across accounts or Regions without CloudTrail Lake |
| No persistent delivery | Logs cannot be exported to long-term storage without a trail |

### What a trail adds

Creating a trail enables ongoing delivery of management events to an S3 bucket at no
CloudTrail charge (first copy per Region is free); you pay only S3 storage. Trails also
support log file validation (SHA-256 + RSA digital signature), which is required by the
HIPAA Config conformance pack rule `cloud-trail-log-file-validation-enabled`.

> "You can deliver one copy of your ongoing management events to your Amazon S3 bucket at
> no charge from CloudTrail by creating a trail, however, there are Amazon S3 storage
> charges."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging.html

### Practical implication for the project

For bucket-level configuration changes (DeleteBucket, PutBucketPolicy, etc.), a new
account is covered by Event History for 90 days by default. For HIPAA's 6-year retention
requirement, a trail is mandatory — Event History alone is insufficient. Create a
multi-Region trail with management events enabled and log file validation on from day one.

Source: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-management-events-with-cloudtrail.html

---

## 3. Protecting the Server Access Log Destination Bucket

The project uses an optional companion S3 bucket to receive server access logs
(`enable_access_logging_bucket=true`). This section details the specific protections
available for that bucket.

### 3.1 The Object Lock Constraint

**Object Lock CANNOT be applied to a bucket that is the destination for S3 server access
logs.** AWS documentation is explicit:

> "S3 buckets with Object Lock can't be used as destination buckets for server access
> logs."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-configure.html

This is a hard platform constraint, not a configuration choice. Object Lock enables WORM
storage. WORM-protecting the server access log bucket directly is therefore not possible.
The workaround is described in section 3.5.

### 3.2 Versioning

Versioning **can** and **should** be enabled on the logging bucket. It is not blocked by
the server-access-log destination constraint.

Benefits for the logging bucket:
- Retains all versions of every log object, protecting against accidental deletion (a
  delete operation adds a delete marker; prior versions remain recoverable).
- Required before you can apply Object Lock on a separate archive bucket fed from this
  bucket.
- Allows recovery of individual overwritten or deleted log objects.

The project already enables versioning on the logging bucket. This is correct.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html

### 3.3 Lifecycle Rules and HIPAA 6-Year Retention

HIPAA's Security Rule (45 CFR § 164.530(j)) requires covered entities to retain
documentation for **six years** from creation or last effective date. The HHS guidance
broadly applies this to security-related records, including audit logs.

S3 Lifecycle rules can enforce a minimum retention period on the logging bucket. AWS
documentation explicitly recommends lifecycle configuration to manage log retention:

> "You can use Amazon S3 Lifecycle configuration to set rules so that Amazon S3
> automatically deletes log objects after a specified period."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/deleting-log-files-lifecycle.html

For HIPAA, configure the lifecycle rule to transition objects rather than delete them
before 6 years have elapsed:

```python
# CDK example: transition logs to cheaper storage, expire after 7 years
from aws_cdk import Duration
import aws_cdk.aws_s3 as s3

logging_bucket = s3.Bucket(
    self, "LoggingBucket",
    versioned=True,
    lifecycle_rules=[
        s3.LifecycleRule(
            id="TransitionToIA",
            transitions=[
                s3.Transition(
                    storage_class=s3.StorageClass.INTELLIGENT_TIERING,
                    transition_after=Duration.days(90),
                )
            ],
            expiration=Duration.days(2557),  # 7 years (provides buffer over 6-year min)
            noncurrent_version_expiration=Duration.days(2557),
        )
    ],
)
```

Note: A lifecycle rule that *expires* objects before 6 years would be a HIPAA violation.
The rule should set a minimum expiration of 2190 days (6 years), with 2557 days (7 years)
recommended to provide margin.

### 3.4 Bucket Policy: Deny Deletion

A bucket policy can deny `s3:DeleteObject` and `s3:DeleteObjectVersion` on the logging
bucket to prevent any principal — including the account owner — from deleting log objects
without first modifying the bucket policy itself:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyLogObjectDeletion",
      "Effect": "Deny",
      "Principal": "*",
      "Action": [
        "s3:DeleteObject",
        "s3:DeleteObjectVersion"
      ],
      "Resource": "arn:aws:s3:::your-logging-bucket/*"
    },
    {
      "Sid": "DenyLifecycleConfigurationChanges",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutLifecycleConfiguration",
      "Resource": "arn:aws:s3:::your-logging-bucket"
    }
  ]
}
```

This is a deterrent control, not an absolute one: an account administrator with
`s3:PutBucketPolicy` can remove or override the policy. Pair with CloudTrail alerting
on `PutBucketPolicy` for the logging bucket to detect any modification.

### 3.5 True WORM for Server Access Logs

Since the logging destination bucket cannot use Object Lock, the approach for achieving
WORM protection of server access logs is a two-stage pipeline:

**Option A — CloudWatch Logs delivery path (recommended for HIPAA):**

1. Deliver server access logs to a **CloudWatch Logs log group** (supports AWS KMS
   encryption, cross-account aggregation, structured JSON format).
2. From CloudWatch Logs, export or stream log records to a **separate S3 archive bucket
   that has Object Lock enabled in COMPLIANCE mode** with a 6-year (or 7-year) retention
   period. This archive bucket is not the direct server access log destination, so the
   Object Lock constraint does not apply.

AWS documentation confirms CloudWatch Logs delivery supports cross-account and
cross-Region aggregation, KMS encryption, and delivery to S3 in JSON or Apache Parquet:

> "CloudWatch Logs ... You can query logs with CloudWatch Logs Insights, aggregate logs
> across accounts and Regions, and encrypt logs with AWS KMS."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html

**Option B — CloudTrail as the primary WORM audit record:**

Use CloudTrail data events as the primary HIPAA audit trail (with log file integrity
validation and the CloudTrail destination bucket protected by Object Lock in COMPLIANCE
mode). S3 server access logs provide supplemental HTTP-level detail but are not relied
upon as the sole compliance record. The CloudTrail bucket itself can use Object Lock
because it is not an S3 server access log destination.

AWS Well-Architected guidance for financial and life sciences workloads recommends this
pattern for immutable audit records:

> "Store immutable audit records in Amazon S3 with S3 Object Lock enabled to enforce
> retention and immutability."

Source: https://docs.aws.amazon.com/wellarchitected/latest/life-sciences-lens/lsrel09-bp04.html

> "With S3 Object Lock, you can securely deliver logs to a designated S3 bucket, and use
> the S3 Object Lock feature to make the logs immutable."

Source: https://docs.aws.amazon.com/wellarchitected/latest/financial-services-industry-lens/fsisec10.html

### 3.6 CDK Patterns

**Logging bucket (versioning + lifecycle, no Object Lock):**

```python
import aws_cdk.aws_s3 as s3
from aws_cdk import Duration, RemovalPolicy

logging_bucket = s3.Bucket(
    self, "AccessLogBucket",
    versioned=True,                          # Required: protects against accidental deletion
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.S3_MANAGED,  # SSE-S3 required; SSE-KMS not supported
    removal_policy=RemovalPolicy.RETAIN,
    lifecycle_rules=[
        s3.LifecycleRule(
            id="RetainLogsMinimum7Years",
            expiration=Duration.days(2557),  # 7 years
            noncurrent_version_expiration=Duration.days(2557),
        )
    ],
)
```

Note: The logging destination bucket must use SSE-S3 encryption, not SSE-KMS. S3 cannot
deliver server access logs to a bucket with SSE-KMS default encryption because the S3
logging principal does not have access to the KMS key.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html

**Object Lock-protected archive bucket (for WORM copies of logs, separate from the
direct server access log destination):**

```python
# Object Lock for COMPLIANCE mode with 7-year retention
archive_bucket = s3.Bucket(
    self, "LogArchiveBucket",
    object_lock_enabled=True,
    object_lock_default_retention=s3.ObjectLockRetention.compliance(
        Duration.days(2557)  # 7 years
    ),
    versioned=True,  # Automatically enabled by Object Lock
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.KMS,
    removal_policy=RemovalPolicy.RETAIN,
)
```

Source: https://constructs.dev/packages/aws-cdk-lib/v/2.268.0?submodule=aws_s3&lang=python

---

## 4. S3 Server Access Logging Completeness vs. CloudTrail Data Events

AWS documentation states:

> "We recommend that you use CloudTrail for logging bucket-level and object-level actions
> for your Amazon S3 resources."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html

### Side-by-side comparison

The following table is drawn directly from official AWS documentation:

| Property | CloudTrail | S3 Server Access Logs |
|---|---|---|
| Integrity validation (digital signature / hash) | Yes | No |
| Guaranteed completeness | Yes (for API calls CloudTrail supports) | No (best-effort) |
| Delivery speed | Data events every ~5 min | Within a few hours |
| Log format | Structured JSON | Space-delimited text (S3 delivery) / JSON (CW Logs) |
| Object Lock parameters, S3 Select properties | Yes | No |
| Lifecycle transitions, expirations, restores | No | Yes |
| Authentication failures (invalid credentials) | No | Yes |
| Subset of objects (prefix-level targeting) | Yes | No |
| Cross-account log delivery | Yes | Yes (CW Logs path only) |
| AWS KMS encryption of logs | Yes | Yes (CW Logs path only) |
| Querying | Athena, CloudTrail Lake SQL | Athena (S3); CW Logs Insights (CW Logs) |

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html

### The completeness gap

S3 server access logging is **explicitly documented as best-effort**:

> "The completeness and timeliness of server logging is not guaranteed. The log record
> for a particular request might be delivered long after the request was actually
> processed, or **it might not be delivered at all**. It is possible that you might even
> see a duplication of a log record."

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html

This means server access logs cannot be used as a substitute for CloudTrail in any audit
or compliance context where completeness is required. HIPAA's audit control requirement
(§164.312(b)) — "implement hardware, software, and/or procedural mechanisms that record
and examine activity in information systems that contain or use ePHI" — requires a
complete, tamper-evident record. Server access logs meet neither criterion on their own:
they are incomplete by design and lack integrity validation.

CloudTrail data events are delivered with a digital signature (SHA-256 + RSA) on each
log file, enabling verification that the file has not been tampered with. Server access
logs have no equivalent mechanism.

### What server access logs capture that CloudTrail does not

Despite their limitations, server access logs capture events that CloudTrail specifically
does not:

1. **Authentication failures** — requests with invalid credentials. CloudTrail does not
   log requests that fail authentication. Server access logs do.
2. **Lifecycle transitions, expirations, and restores** — S3-generated events that have
   no CloudTrail representation.
3. **HTTP-level metadata** — `Object Size`, `Total Time`, `Turn-Around Time`,
   `HTTP Referer`.

For incident response after a PHI breach, authentication failures and HTTP referrer data
can be crucial forensic information not available in CloudTrail.

### HIPAA assessment

S3 server access logging is **not a complete substitute** for CloudTrail data events for
HIPAA audit purposes. The gaps are:

- No integrity validation — logs can be altered without detection.
- Best-effort delivery — records may be missing entirely.
- No coverage of authentication failures from the CloudTrail side means neither system
  alone captures all relevant events.

**Recommendation:** Enable both. Use CloudTrail data events as the primary HIPAA
compliance record. Use S3 server access logs delivered via CloudWatch Logs as the
secondary operational and forensic record.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html

---

## 5. Practical Recommendations

### For the `enable_access_logging_bucket` feature

| Control | Status | Notes |
|---|---|---|
| Versioning on logging bucket | Recommended | Already in project; retain |
| Object Lock on logging bucket | Not possible | AWS constraint: Object Lock buckets cannot be server access log destinations |
| SSE-S3 on logging bucket | Required | SSE-KMS is not supported for server access log delivery |
| Lifecycle rule ≥ 6-year retention | Required for HIPAA | Add 7-year expiration; do not expire before 2190 days |
| Bucket policy denying deletion | Recommended | Deterrent control; pair with CloudTrail alarm on PutBucketPolicy |
| CloudWatch Logs delivery path | Recommended for WORM | Enables KMS encryption; logs can be archived to a separate Object Lock bucket |

### For HIPAA audit completeness

- Create a multi-Region CloudTrail trail with management events and log file validation
  enabled on day one. Management events are free for the first trail per Region.
- Add CloudTrail data events for write and delete operations on PHI buckets. Scope with
  advanced event selectors to control cost on high-throughput buckets.
- Set a 7-year retention period on the CloudTrail S3 destination bucket and protect it
  with Object Lock in COMPLIANCE mode. The CloudTrail bucket is not a server access log
  destination, so the Object Lock constraint does not apply.
- Enable S3 server access logging and deliver to CloudWatch Logs for authentication
  failure capture, HTTP-level detail, and forensic support.
- Do not rely on Event History alone for management event retention — it only covers 90
  days.

### Cost management for high-throughput buckets

- Use advanced event selectors to scope CloudTrail data events to write-only operations
  (exclude `GetObject`) if read auditing is not required by the specific regulatory
  context.
- For read auditing, server access logging (near-zero delivery cost) provides operational
  visibility, but document explicitly that it is supplemental and not the HIPAA audit
  record.
- Enable S3 Bucket Keys to reduce KMS API call volume and cost on the PHI bucket itself.

Sources:
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-trail-manage-costs.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-management-events-with-cloudtrail.html
- https://docs.aws.amazon.com/awscloudtrail/latest/userguide/how-cloudtrail-works.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-configure.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/deleting-log-files-lifecycle.html
- https://docs.aws.amazon.com/wellarchitected/latest/life-sciences-lens/lsrel09-bp04.html
- https://docs.aws.amazon.com/wellarchitected/latest/financial-services-industry-lens/fsisec10.html
- https://constructs.dev/packages/aws-cdk-lib/v/2.268.0?submodule=aws_s3&lang=python
- https://aws.amazon.com/cloudtrail/pricing/
