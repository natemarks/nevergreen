# S3 Security for HIPAA PHI: Engineer's Reference

This document consolidates official AWS guidance on securing S3 buckets that store
extremely sensitive data, including HIPAA Protected Health Information (PHI). Every
claim cites its source URL. Read it end-to-end before designing a PHI-storing bucket,
and re-read the HIPAA Compliance section for program-level obligations.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Encryption](#2-encryption)
   - 2.1 [Default Encryption Baseline](#21-default-encryption-baseline)
   - 2.2 [SSE-S3 — S3-Managed Keys](#22-sse-s3--s3-managed-keys)
   - 2.3 [SSE-KMS — AWS KMS Keys](#23-sse-kms--aws-kms-keys)
   - 2.4 [DSSE-KMS — Dual-Layer KMS](#24-dsse-kms--dual-layer-kms)
   - 2.5 [SSE-C — Customer-Provided Keys](#25-sse-c--customer-provided-keys)
   - 2.6 [KMS Key Types: AWS-Managed vs. Customer-Managed](#26-kms-key-types-aws-managed-vs-customer-managed)
   - 2.7 [Envelope Encryption — How SSE-KMS Works Internally](#27-envelope-encryption--how-sse-kms-works-internally)
   - 2.8 [S3 Bucket Keys — Cost Optimization](#28-s3-bucket-keys--cost-optimization)
   - 2.9 [Encryption in Transit](#29-encryption-in-transit)
   - 2.10 [Practical Protection Model — What the Encryption Actually Defends Against](#210-practical-protection-model--what-the-encryption-actually-defends-against)
   - 2.11 [CMK Maintenance and Operational Workflow](#211-cmk-maintenance-and-operational-workflow)
3. [Access Control](#3-access-control)
   - 3.1 [Block Public Access](#31-block-public-access)
   - 3.2 [S3 Object Ownership and ACLs](#32-s3-object-ownership-and-acls)
   - 3.3 [Bucket Policies](#33-bucket-policies)
   - 3.4 [IAM Identity-Based Policies](#34-iam-identity-based-policies)
   - 3.5 [VPC Endpoints — Network Isolation](#35-vpc-endpoints--network-isolation)
   - 3.6 [Service Control Policies and Resource Control Policies](#36-service-control-policies-and-resource-control-policies)
4. [Audit and Logging](#4-audit-and-logging)
   - 4.1 [CloudTrail — Authoritative Audit Trail](#41-cloudtrail--authoritative-audit-trail)
   - 4.2 [S3 Server Access Logging](#42-s3-server-access-logging)
   - 4.3 [Choosing Between CloudTrail and Server Access Logs](#43-choosing-between-cloudtrail-and-server-access-logs)
5. [Data Integrity and Retention](#5-data-integrity-and-retention)
   - 5.1 [S3 Versioning](#51-s3-versioning)
   - 5.2 [S3 Object Lock — WORM Storage](#52-s3-object-lock--worm-storage)
6. [HIPAA Compliance on AWS](#6-hipaa-compliance-on-aws)
   - 6.1 [S3 is HIPAA-Eligible](#61-s3-is-hipaa-eligible)
   - 6.2 [Business Associate Addendum (BAA)](#62-business-associate-addendum-baa)
   - 6.3 [Shared Responsibility Model](#63-shared-responsibility-model)
   - 6.4 [AWS Config HIPAA Conformance Pack](#64-aws-config-hipaa-conformance-pack)
   - 6.5 [Security Hub Controls Relevant to S3](#65-security-hub-controls-relevant-to-s3)
7. [Recommended Configuration Checklist](#7-recommended-configuration-checklist)

---

## 1. Overview

Amazon S3 is a HIPAA-eligible service. AWS will sign a Business Associate Addendum
(BAA) covering S3. However, eligibility alone does not make a bucket compliant — the
customer is responsible for configuring the bucket correctly.

The controls required by HIPAA's Security Rule (45 CFR Part 164) map to four S3
capability areas:

| HIPAA Requirement | S3 Controls |
|---|---|
| Encryption of ePHI at rest (§164.312(a)(2)(iv)) | SSE-KMS with CMK, DSSE-KMS |
| Encryption in transit (§164.312(e)(2)(ii)) | TLS-enforcing bucket policy |
| Access controls / minimum necessary (§164.312(a)(1)) | Bucket policies, IAM, Block Public Access |
| Audit controls (§164.312(b)) | CloudTrail data events, Server access logs |
| Integrity controls (§164.312(c)(1)) | Object Lock, Versioning, CloudTrail log validation |

Sources:
- S3 compliance programs: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-compliance.html
- HIPAA Config conformance pack: https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html

---

## 2. Encryption

### 2.1 Default Encryption Baseline

Since January 5, 2023, **all new S3 object uploads are automatically encrypted at no
additional cost**. The default algorithm is SSE-S3 (AES-256-GCM). This applies to every
bucket unless overridden by the bucket's default encryption configuration.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html

For PHI, the default SSE-S3 satisfies the "encryption at rest" requirement, but
SSE-KMS with a customer-managed key (CMK) is strongly preferred because it provides
independent key management, access auditing via CloudTrail, and the ability to revoke
access to the key entirely.

### 2.2 SSE-S3 — S3-Managed Keys

**How it works:** S3 encrypts each object with a unique key using
**256-bit AES-GCM**. The per-object key is itself encrypted by a root key that S3
rotates regularly. All key material is managed entirely by S3.

**Characteristics:**
- No additional cost.
- No customer control over key policies or rotation schedule.
- Cannot be used to audit individual decrypt operations (no CloudTrail visibility for
  key usage).
- Cannot be used to revoke access to data by disabling a key.
- No cross-account key restrictions.

**Bucket policy to enforce SSE-S3 on uploads:**

```json
{
  "Version": "2012-10-17",
  "Id": "PutObjectPolicy",
  "Statement": [
    {
      "Sid": "DenyObjectsThatAreNotSSES3",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::your-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": "AES256"
        }
      }
    }
  ]
}
```

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html

**PHI assessment:** Acceptable minimum baseline. Insufficient on its own for environments
requiring independent key auditability or revocation capability.

### 2.3 SSE-KMS — AWS KMS Keys

**How it works:** S3 calls AWS KMS to generate a data encryption key for each object
(or for a group of objects if Bucket Keys are enabled). S3 encrypts the object with
the plaintext data key, discards the plaintext key immediately, and stores the KMS-encrypted
copy of the data key alongside the object.

**Characteristics:**
- Full CloudTrail logging of every `GenerateDataKey` (on write) and `Decrypt` (on read)
  KMS API call — provides per-principal, per-object key-usage audit trail.
- Key policy and IAM policy controls who can use the KMS key.
- Key can be disabled or scheduled for deletion to immediately block all future decryption.
- Additional per-request KMS API charges apply (mitigated by S3 Bucket Keys).
- Objects encrypted with the AWS-managed key (`aws/s3`) cannot be shared cross-account;
  use a CMK for cross-account access.

**Required IAM permissions:**
- `kms:GenerateDataKey` — needed to write (PutObject).
- `kms:Decrypt` — needed to read (GetObject) or to perform multipart uploads.

**Bucket policy to enforce SSE-KMS on all uploads:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNonKMSEncryption",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::your-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": "aws:kms"
        }
      }
    }
  ]
}
```

To also require a **specific CMK** (preventing accidental use of the AWS-managed key):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RequireSpecificKMSKey",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::your-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption-aws-kms-key-id":
            "arn:aws:kms:us-east-1:111122223333:key/key-id"
        }
      }
    }
  ]
}
```

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html

**PHI assessment:** Strongly recommended for PHI. Use a CMK for full auditability,
revocation capability, and cross-account sharing.

### 2.4 DSSE-KMS — Dual-Layer KMS

Dual-layer server-side encryption with AWS KMS (DSSE-KMS) applies **two independent layers
of encryption** to each object, each governed by its own KMS data key derived from the
same (or different) KMS key. This exceeds the requirements of most frameworks but is
available when regulations or internal policies mandate dual-layer protection.

Security Hub control S3.17 checks that buckets are encrypted with SSE-KMS or DSSE-KMS.

Source: https://docs.aws.amazon.com/securityhub/latest/userguide/s3-controls.html

### 2.5 SSE-C — Customer-Provided Keys

**How it works:** The caller sends the AES-256 encryption key in the request header with
every PUT and GET. S3 uses the key to encrypt or decrypt the object and **immediately
discards the key** — it is never stored by AWS. The caller is entirely responsible for
key storage, rotation, and distribution.

**Important behavioral change (April 2026):** SSE-C is **disabled by default** on all new
general purpose buckets and on existing buckets with no SSE-C objects. To use SSE-C you
must explicitly set `BlockedEncryptionTypes` to `NONE` via `PutBucketEncryption`.

**Limitations that make SSE-C problematic for PHI:**
- Requires the encryption key on every read and write request — impractical for shared
  access, Lambda, or other AWS services operating on the data.
- If the key is lost, the object is permanently unrecoverable.
- No AWS-side audit trail of key usage.
- S3 rejects SSE-C GET requests through Object Lambda Access Points to prevent key logging.
- AWS broadly recommends SSE-KMS over SSE-C for any modern workload.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerSideEncryptionCustomerKeys.html

**PHI assessment:** Not recommended for PHI workloads. The operational burden, lack of
auditability, and risk of key loss outweigh the theoretical control advantage.

### 2.6 KMS Key Types: AWS-Managed vs. Customer-Managed

| Property | AWS-Managed Key (`aws/s3`) | Customer-Managed Key (CMK) |
|---|---|---|
| Created by | AWS, automatically on first SSE-KMS use | You |
| Key policy | AWS-controlled; not editable | Fully editable |
| Rotation | Automatic, every year | Manual or automatic (configurable) |
| Disable / delete | No | Yes |
| Cross-account access | Not supported | Supported via key policy |
| Audit in CloudTrail | Yes (key usage) | Yes (key usage) |
| Monthly key fee | None | Yes (~$1/key/month) |
| Count against KMS quotas | No (resource quota) | Yes |
| `KeyManager` field (DescribeKey) | `AWS` | `CUSTOMER` |

Key points for PHI:

- **Use a CMK.** The ability to disable or delete the key, define fine-grained key
  policies, and cross-account access control are all essential for regulated workloads.
- CMKs appear under **Customer managed keys** in the KMS console.
- AWS-managed keys appear as `aws/s3` under **AWS managed keys**.
- Customer managed keys incur a per-request fee above the free tier in addition to the
  monthly key fee.

Source: https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html

### 2.7 Envelope Encryption — How SSE-KMS Works Internally

AWS KMS uses **envelope encryption** to protect S3 data. The pattern has two layers:

1. **Data Key (DEK):** A unique AES-256 symmetric key generated by KMS for each
   encryption operation. The DEK encrypts the actual S3 object data. S3 discards the
   plaintext DEK from memory as soon as encryption completes.

2. **Key Encryption Key (KMS Key / KEK):** The CMK or AWS-managed key stored in KMS
   HSMs. This key never leaves KMS in plaintext. KMS uses it to encrypt the DEK.
   S3 stores the KMS-encrypted DEK as metadata alongside the object.

**SSE-KMS encryption workflow (step by step):**

1. S3 requests a plaintext DEK and an encrypted copy from KMS.
2. KMS generates a DEK, encrypts it under the KMS key (using AES-256-GCM inside an HSM),
   and returns both copies to S3.
3. S3 encrypts the object data using the plaintext DEK.
4. S3 discards the plaintext DEK from memory immediately after use.
5. S3 stores the KMS-encrypted DEK as object metadata.

**Decryption workflow:**

1. S3 sends the encrypted DEK to KMS in a `Decrypt` request.
2. KMS verifies the caller has `kms:Decrypt` permission on the KMS key, decrypts the
   DEK inside the HSM, and returns the plaintext DEK to S3.
3. S3 decrypts the object, discards the plaintext DEK from memory.

**Why this matters for PHI:** The KMS key (KEK) never leaves the HSM. An attacker who
obtains a copy of the encrypted S3 object and the encrypted DEK cannot decrypt the data
without access to the KMS key — which requires passing KMS IAM/key policy checks that
are independently audited in CloudTrail.

Sources:
- Envelope encryption workflow: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html
- KMS cryptography internals (AES-256-GCM, NIST SP800-90A DRBG, HSM architecture):
  https://docs.aws.amazon.com/kms/latest/developerguide/kms-cryptography.html

### 2.8 S3 Bucket Keys — Cost Optimization

By default, every S3 object PUT with SSE-KMS generates a separate KMS API call.
**S3 Bucket Keys** reduce this by generating a short-lived bucket-level data key inside
S3, which is used to derive per-object keys without calling KMS for each object. This
can reduce KMS API call counts — and therefore cost — by orders of magnitude for
high-throughput buckets.

Bucket Keys are compatible with CMKs and do not weaken the security model. They are
recommended for any PHI bucket with significant write throughput.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html
(see "Amazon S3 Bucket Keys" section)

### 2.9 Encryption in Transit

All S3 endpoints support HTTPS/TLS. Enforce it with a bucket policy:

**Deny all non-HTTPS traffic (`aws:SecureTransport`):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RestrictToTLSRequestsOnly",
      "Action": "s3:*",
      "Effect": "Deny",
      "Resource": [
        "arn:aws:s3:::your-bucket",
        "arn:aws:s3:::your-bucket/*"
      ],
      "Condition": {
        "Bool": {
          "aws:SecureTransport": "false"
        }
      },
      "Principal": "*"
    }
  ]
}
```

**Require TLS 1.3 minimum (stricter):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureConnections",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::your-bucket",
        "arn:aws:s3:::your-bucket/*"
      ],
      "Condition": {
        "NumericLessThan": {
          "s3:TlsVersion": "1.3"
        }
      }
    }
  ]
}
```

Use `s3:TlsVersion` to enforce a specific minimum version; use `aws:SecureTransport`
when you only need to ban plaintext HTTP.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryptionInTransit.html

### 2.10 Practical Protection Model — What the Encryption Actually Defends Against

Applications using SSE-KMS or DSSE-KMS with a CMK do not need to handle key material
themselves — S3 calls KMS on the caller's behalf using the caller's IAM identity. The
CMK never leaves the KMS HSM. This model provides layered protection beyond simple
"data is encrypted at rest":

| Threat | How the model defends |
|---|---|
| Stolen storage hardware or AWS-internal access | The CMK lives in the KMS HSM and never leaves it. Raw S3 storage bytes and the encrypted DEK stored in object metadata are useless without a KMS decrypt call. |
| Misconfigured bucket policy / accidental public access | KMS authorization is a separate, independent gate. An unauthenticated caller who can reach the object (e.g., via a misconfigured public bucket) still cannot decrypt it without passing KMS IAM checks. |
| Cross-account data leak via overshared bucket | Two independent permission grants are required: the S3 bucket policy must allow the cross-account principal, **and** the CMK key policy must also explicitly grant it `kms:Decrypt`. A permissive bucket policy alone is insufficient. |
| Unauthorized AWS service accessing data | IAM `kms:Decrypt` and `kms:GenerateDataKey` must be explicitly granted per identity. Lambda, Glue, Athena, and other services operating on your data require separate, scoped KMS grants. |
| Breach detected, need immediate lockout | Disabling the CMK instantly prevents all future KMS `Decrypt` calls. Every object in every SSE-KMS bucket protected by that key becomes unreadable — without deleting a single object. Re-enabling the key restores access. |
| Audit trail for PHI access | Every `s3:GetObject` on an SSE-KMS object produces a `kms:Decrypt` call that CloudTrail records in near-real-time. This trail is independent of S3 server access logs and is tamper-evident. |

**Why applications don't need the CMK ARN at runtime:** The bucket's default encryption
configuration specifies the CMK. When an application calls `s3:PutObject`, S3 requests
a DEK from KMS using the bucket's configured CMK automatically. When the application
calls `s3:GetObject`, S3 sends the object's encrypted DEK to KMS for decryption. The
application's IAM role must have `kms:GenerateDataKey` (write) and `kms:Decrypt` (read)
on the CMK, but the ARN never needs to appear in application code.

The CMK ARN is only needed at **infrastructure setup time** — when creating the bucket,
writing the key policy, and writing the bucket policy condition that pins the CMK.

Sources:
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html
- https://docs.aws.amazon.com/kms/latest/developerguide/kms-cryptography.html
- https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/sec_protect_data_rest_key_mgmt.html

### 2.11 CMK Maintenance and Operational Workflow

#### Key rotation

**Automatic rotation** rotates the cryptographic key material while keeping the same
key ARN, key ID, key policies, and all IAM grants. All existing ciphertext remains
decryptable — KMS automatically uses whichever version of the key material was in effect
when an object was encrypted. S3 objects are **not** re-encrypted; rotation only affects
future encryption operations.

- Default period: **365 days**
- Configurable range: **90–2560 days**
- Enable via the KMS console or: `aws kms enable-key-rotation --key-id <id> --rotation-period-in-days 365`
- KMS retains all past key material versions indefinitely for decryption of existing objects.

Source: https://docs.aws.amazon.com/kms/latest/developerguide/rotating-keys-enable.html

**On-demand rotation** rotates key material immediately, independent of the automatic
schedule. Use it for incident response when you suspect key material compromise. An
on-demand rotation does not reset the automatic rotation clock. Limit: 25 on-demand
rotations per key lifetime. Requires `kms:RotateKeyOnDemand`.

Source: https://docs.aws.amazon.com/kms/latest/developerguide/rotating-keys-on-demand.html

**What rotation does NOT do:**
- Does not change the key ARN or key ID.
- Does not re-encrypt any S3 objects already stored.
- Does not require any update to application config, IAM policies, bucket policies, or
  stored ARN references.
- Does not mitigate exposure of existing ciphertext — only future encryption uses the
  new key material.

#### Storing the CMK ARN

A CMK ARN is a **resource identifier, not a secret credential**. Do not store it in
AWS Secrets Manager. The appropriate store is **SSM Parameter Store** as a plain
`String` parameter (no SecureString encryption needed):

```
/myapp/prod/phi-bucket-cmk-arn   (type: String)
```

Restrict read access to the SSM path via IAM for least privilege. No rotation lambda
is needed or appropriate — because KMS rotation preserves the ARN, a stored CMK ARN
never becomes stale from rotation. The only scenario requiring an ARN update is manual
key replacement (a deliberate operational decision, not automation).

AWS's own solutions (e.g., Automated Security Response on AWS) follow this pattern,
storing CMK ARNs in SSM Parameter Store as plain String parameters.

Source: https://docs.aws.amazon.com/solutions/latest/automated-security-response-on-aws/aws-systems-manager-parameter-store.html

#### Full maintenance cadence

| Task | Frequency | Automation |
|---|---|---|
| Key material rotation | 365 days (or per policy; configurable 90–2560) | KMS automatic rotation — enable once at key creation |
| On-demand rotation (incident response) | As needed (suspected compromise) | Manual trigger; max 25 per key |
| Key policy review (stale principals, departed roles) | Quarterly or annually | IAM Access Analyzer detects overly broad policies continuously |
| CloudTrail KMS + S3 data event review | Continuous | CloudWatch alarms on `kms:Disable`, `ScheduleKeyDeletion`, unexpected `kms:Decrypt` volume |
| Security Hub KMS controls (KMS.1, KMS.2, KMS.4) | Continuous | Security Hub CSPM — runs automatically; KMS.4 alerts when rotation is disabled |
| Bucket policy and IAM policy review | Annually (HIPAA periodic risk analysis) | AWS Config HIPAA conformance pack |
| Key deletion safety | Continuous | CloudTrail alarm on `ScheduleKeyDeletion`; configurable waiting period 7–30 days (default 30) before deletion completes |

The continuous automation layer (Security Hub + CloudTrail alarms + IAM Access Analyzer)
covers most ongoing risk. The remaining human task is periodic review of key and bucket
policies to remove stale grants.

Sources:
- https://docs.aws.amazon.com/kms/latest/developerguide/rotate-keys.html
- https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/sec_protect_data_rest_key_mgmt.html
- https://docs.aws.amazon.com/prescriptive-guidance/latest/aws-kms-best-practices/data-protection-encryption.html

---

## 3. Access Control

### 3.1 Block Public Access

Block Public Access (BPA) is a set of four independent settings that override bucket
and access point policies to prevent public access regardless of how resource policies
are written. Since April 2023, BPA is **enabled by default on all new buckets**.

The four settings:

| Setting | What it does |
|---|---|
| `BlockPublicAcls` | Ignores ACLs that would grant public access; rejects new public ACLs |
| `IgnorePublicAcls` | Ignores all existing public ACLs |
| `BlockPublicPolicy` | Rejects bucket policies that would grant public access |
| `RestrictPublicBuckets` | Restricts access to only AWS services and authorized principals, even if a public policy exists |

**Recommendation for PHI:** Enable **all four settings** at both the account level and
the individual bucket level. Account-level settings apply globally across all Regions.
If your organization uses AWS Organizations, configure organization-level BPA policies
for centralized enforcement.

Evaluation order: S3 applies the most restrictive combination of organization, account,
and bucket-level settings. An organization-level BPA policy that is enabled overrides
a bucket-level setting that is disabled.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html

Security Hub control S3.8 checks that all four BPA settings are enabled on every bucket.

### 3.2 S3 Object Ownership and ACLs

**Bucket owner enforced** is the recommended Object Ownership setting. When set:
- All ACLs are disabled and ignored.
- All objects in the bucket are owned by the bucket account, regardless of who uploaded them.
- Access is controlled exclusively by IAM policies and bucket policies.

ACLs predate IAM-based access control and are a common source of over-permissive access.
For PHI buckets, disable ACLs entirely by setting Object Ownership to
**Bucket owner enforced**.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html

### 3.3 Bucket Policies

Bucket policies are IAM resource-based policies attached to a bucket. They are the
primary mechanism for:

- Denying non-compliant requests (no TLS, no KMS encryption).
- Restricting access to specific IAM principals, VPC endpoints, VPCs, or IP ranges.
- Granting cross-account access.

**PHI-specific policy patterns:**

**1. Deny unencrypted uploads and non-HTTPS access (combined):**

```json
{
  "Version": "2012-10-17",
  "Id": "SSEAndSSLPolicy",
  "Statement": [
    {
      "Sid": "DenyUnEncryptedObjectUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::your-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": "aws:kms"
        }
      }
    },
    {
      "Sid": "DenyInsecureConnections",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": "arn:aws:s3:::your-bucket/*",
      "Condition": {
        "Bool": {
          "aws:SecureTransport": false
        }
      }
    }
  ]
}
```

**2. Restrict access to a specific VPC endpoint:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Allow-access-to-specific-VPCE",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::your-bucket",
        "arn:aws:s3:::your-bucket/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:sourceVpce": "vpce-1a2b3c4d"
        }
      }
    }
  ]
}
```

**3. Restrict to a specific VPC (all endpoints in that VPC):**

Replace `aws:sourceVpce` with `aws:sourceVpc: "vpc-111bbb22"`.

Source: https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html

**Important caveat:** Bucket policies apply only to objects owned by the bucket owner.
With **Bucket owner enforced** Object Ownership (recommended), all objects are
automatically owned by the bucket account, so the bucket policy applies universally.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html

### 3.4 IAM Identity-Based Policies

IAM identity-based policies attached to roles, users, or groups control which principals
can call which S3 API actions. For PHI:

- Follow **least privilege**: grant only the specific actions (e.g., `s3:GetObject`,
  `s3:PutObject`) on the specific bucket ARN and prefix needed.
- Grant `kms:GenerateDataKey` and `kms:Decrypt` on the CMK ARN explicitly; do not
  use wildcards.
- Use IAM Access Analyzer for S3 to continuously monitor for unintended external access.
- Prefer IAM roles over long-lived IAM user credentials.

Key IAM permissions for SSE-KMS:
- `s3:PutObject` — to write objects.
- `kms:GenerateDataKey` — required to encrypt (write).
- `kms:Decrypt` — required to decrypt (read).
- Without both KMS permissions the corresponding S3 operation fails.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/security_iam_service-with-iam.html

### 3.5 VPC Endpoints — Network Isolation

S3 supports two types of VPC endpoints:

| Type | Description | Cost |
|---|---|---|
| **Gateway endpoint** | Routes S3 traffic within the VPC via the route table; no data traverses the public internet | No additional charge |
| **Interface endpoint (AWS PrivateLink)** | Provisions an ENI with a private IP inside your VPC subnet for S3 access from on-premises or across accounts | Per-hour + per-GB charges |

**For PHI workloads:** Deploy a gateway VPC endpoint in every VPC that needs S3 access.
Combine with a bucket policy using `aws:sourceVpce` or `aws:sourceVpc` to ensure PHI
buckets are only reachable from within approved VPCs — never over the public internet.

Traffic routed through VPC endpoints does not leave the AWS network.

Source:
- Gateway/interface endpoint types: https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html
- Bucket policy with VPC endpoint conditions: https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html

### 3.6 Service Control Policies and Resource Control Policies

For organizations managing multiple AWS accounts, AWS Organizations provides two
policy types that apply above the IAM layer:

- **Service Control Policies (SCPs):** Attached to OUs or accounts; restrict what IAM
  principals in those accounts can do. Use to mandate KMS encryption and HTTPS across
  the entire organization.
- **Resource Control Policies (RCPs):** Applied to resources (new as of 2024); restrict
  what any principal can do to a resource, regardless of their account. RCPs can enforce
  S3 bucket policies without modifying each bucket individually.

Both are referenced in the S3 encryption-in-transit documentation as valid enforcement
mechanisms alongside bucket policies.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryptionInTransit.html

---

## 4. Audit and Logging

### 4.1 CloudTrail — Authoritative Audit Trail

CloudTrail is the **recommended primary audit mechanism** for S3. It captures two
categories of S3 events:

**Management events (free, delivered every ~15 minutes):**
- Bucket-level operations: `CreateBucket`, `DeleteBucket`, `PutBucketPolicy`,
  `PutBucketEncryption`, `PutBucketVersioning`, etc.
- Enabled by default in any CloudTrail trail.

**Data events (additional charge, delivered every ~5 minutes):**
- Object-level operations: `GetObject`, `PutObject`, `DeleteObject`,
  `HeadObject`, `CopyObject`, etc.
- Must be explicitly enabled on a trail or via EventBridge.
- **Required for HIPAA audit controls** — without data events you have no record of who
  accessed which PHI object and when.

**CloudTrail capabilities relevant to PHI:**
- Digital signature / hash validation of log files (SHA-256 + RSA) to detect tampering.
  Enable **Log File Validation** on every trail.
- Integration with CloudWatch Logs, EventBridge, and Athena for querying.
- Captures `AccessDenied` authorization failures and anonymous user requests.
- Does **not** capture authentication failures (invalid credentials) or HTTP 301
  redirect errors.
- KMS API calls (`GenerateDataKey`, `Decrypt`) generated by SSE-KMS are also logged in
  CloudTrail, providing a complete record of every object read/write against the CMK.

**Encrypt the CloudTrail trail itself:** The HIPAA Config conformance pack requires
`cloud-trail-encryption-enabled` — enable SSE-KMS on the trail's destination bucket.

Sources:
- Logging options overview: https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html
- CloudTrail S3 logging guide: https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging.html
- HIPAA Config rule for CloudTrail encryption: https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html

### 4.2 S3 Server Access Logging

Server access logging captures detailed, space-delimited records of every HTTP request
to a bucket. Delivery is **best-effort** (within a few hours; not guaranteed to be
complete; may contain duplicates). It is supplemental to CloudTrail, not a replacement.

**Two delivery paths:**

| Path | Format | Encryption | Cross-account | Querying |
|---|---|---|---|---|
| S3 bucket (same Region/account) | Space-delimited text | SSE-S3 only | No | Amazon Athena |
| Amazon CloudWatch Logs | Structured JSON | AWS KMS (configurable) | Yes | CloudWatch Logs Insights |

**Notable fields in server access logs not available in CloudTrail:**
- `Object Size`, `Total Time`, `Turn-Around Time`, `HTTP Referer`
- Authentication failures (requests with invalid credentials)
- S3 Lifecycle transitions, expirations, and restores

**Caveat for logging bucket:** If the destination bucket uses SSE-KMS default
encryption, S3 may deliver log objects encrypted with a key you cannot access. The
**destination bucket for server access logs must use SSE-S3** (not SSE-KMS) as its
default encryption.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html

### 4.3 Choosing Between CloudTrail and Server Access Logs

| Need | Use |
|---|---|
| Authoritative, tamper-evident audit trail | CloudTrail (with log file validation) |
| Object-level API auditing for compliance | CloudTrail data events |
| Near-real-time alerting on S3 events | CloudTrail + EventBridge |
| HTTP-level details (latency, referrer) | Server access logs |
| Capturing authentication failures | Server access logs |
| Lifecycle / expiration events | Server access logs |
| Cost-effective general audit | CloudTrail management events (free) + selective data events |

**Recommendation for PHI:** Enable both. Use CloudTrail data events as the primary
compliance record. Use server access logs via CloudWatch Logs (JSON, KMS-encrypted,
queryable with CloudWatch Logs Insights) as a secondary operational record.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html

---

## 5. Data Integrity and Retention

### 5.1 S3 Versioning

Enable versioning on all PHI buckets. Versioning:
- Retains all versions of every object, protecting against accidental or malicious deletion.
- Is required before enabling S3 Object Lock.
- Allows point-in-time recovery of PHI data.

### 5.2 S3 Object Lock — WORM Storage

S3 Object Lock prevents objects from being overwritten or deleted for a configurable
period or indefinitely. It implements **write-once-read-many (WORM)** storage.

Object Lock is assessed by Cohasset Associates for environments subject to SEC 17a-4,
CFTC, and FINRA regulations. HIPAA does not mandate WORM, but Object Lock can serve
as a technical safeguard for integrity controls (§164.312(c)(1)).

**Two retention mechanisms:**

**Retention period:** A fixed-duration lock on an object version. Two modes:

| Mode | Protection level |
|---|---|
| **COMPLIANCE** | No user — including the AWS root account — can delete or overwrite the object before the Retain Until Date. Retention mode cannot be changed; retention period cannot be shortened. The only way to delete a compliance-locked object early is to delete the AWS account itself. |
| **GOVERNANCE** | Protects against most deletions, but users with `s3:BypassGovernanceRetention` permission can override. Useful for testing retention periods before applying compliance mode. |

**Legal hold:** An indefinite lock with no expiration date. Remains in effect until
explicitly removed by a principal with `s3:PutObjectLegalHold` permission. Independent
of any retention period on the same object version.

**To use Object Lock:**
1. Enable Object Lock when creating the bucket (cannot be enabled on an existing bucket).
2. S3 automatically enables versioning.
3. Set a default retention period at the bucket level, or apply individual retention
   settings per object version.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html

---

## 6. HIPAA Compliance on AWS

### 6.1 S3 is HIPAA-Eligible

Amazon S3 is included in AWS's HIPAA-eligible services. Third-party audit reports
confirming S3's compliance posture (SOC 2, ISO 27001, FedRAMP High, HIPAA) are
available for download via **AWS Artifact**.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-compliance.html

The current list of HIPAA-eligible services is maintained at:
https://aws.amazon.com/compliance/hipaa-eligible-services-reference/

### 6.2 Business Associate Addendum (BAA)

A **Business Associate Addendum (BAA)** is required before storing PHI on any
AWS service. The BAA is a standardized AWS agreement covering covered entities
and business associates. It is executed through **AWS Artifact** under
"Agreements → Business Associate Addendum."

PHI must only be processed and stored in AWS accounts that have an active BAA. Storing
PHI in an account without a BAA is a HIPAA violation regardless of technical controls.

Sources:
- Managing agreements in AWS Artifact: https://docs.aws.amazon.com/artifact/latest/ug/managing-agreements.html
- HIPAA BAA overview: https://docs.aws.amazon.com/cloudshell/latest/userguide/compliance-validation.html

### 6.3 Shared Responsibility Model

AWS's responsibility (covered by BAA):
- Physical security of data centers.
- Hardware and hypervisor security.
- Managed service security controls.
- Availability, durability, and internal encryption mechanisms of S3.

Customer's responsibility:
- Configuring encryption (choosing SSE-KMS vs. SSE-S3, managing CMKs).
- Configuring access controls (bucket policies, IAM, BPA).
- Enabling and retaining audit logs (CloudTrail data events).
- Training workforce, conducting risk analysis (§164.308(a)(1)(ii)(A)).
- Incident response procedures.
- Ensuring PHI is only in BAA-covered accounts.

Source: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-compliance.html

### 6.4 AWS Config HIPAA Conformance Pack

AWS provides a pre-built Config conformance pack that maps HIPAA Security Rule controls
to AWS Config managed rules. Relevant S3-related rules in the pack include:

| HIPAA Control | Config Rule | Requirement |
|---|---|---|
| §164.312(a)(2)(iv) — Encryption at rest | `s3-bucket-server-side-encryption-enabled` | S3 buckets must have default encryption enabled or a deny-unencrypted policy |
| §164.308(a)(1)(ii)(B) — Risk management | `cloud-trail-encryption-enabled` | CloudTrail logs must be KMS-encrypted |
| §164.308(a)(1)(ii)(B) | `cloud-trail-log-file-validation-enabled` | Log file validation must be on (SHA-256 + RSA integrity checking) |
| §164.312(e)(2)(ii) — Encryption in transit | S3 bucket policy check | Bucket policies must deny non-HTTPS requests |

The conformance pack template is on GitHub:
https://github.com/awslabs/aws-config-rules/blob/master/aws-config-conformance-packs/Operational-Best-Practices-for-HIPAA-Security.yaml

Source: https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html

### 6.5 Security Hub Controls Relevant to S3

AWS Security Hub's Foundational Security Best Practices (FSBP) standard includes the
following S3 controls, all relevant to PHI buckets:

| Control | Requirement |
|---|---|
| S3.3 | Buckets must block public write access |
| S3.8 | All four Block Public Access settings must be enabled |
| S3.15 | Object Lock should be enabled |
| S3.17 | Buckets must be encrypted with SSE-KMS or DSSE-KMS |

Source: https://docs.aws.amazon.com/securityhub/latest/userguide/s3-controls.html

---

## 7. Recommended Configuration Checklist

Use this checklist when provisioning an S3 bucket for HIPAA PHI.

### AWS Account Level
- [ ] Active BAA on file in AWS Artifact for this account.
- [ ] CloudTrail organization trail or account trail with **management events** enabled.
- [ ] CloudTrail **data events** enabled for S3 (all buckets or targeted to PHI buckets).
- [ ] CloudTrail log file validation enabled.
- [ ] CloudTrail destination bucket encrypted with KMS.
- [ ] Block Public Access enabled at the account level (all four settings).

### KMS Key
- [ ] Create a dedicated **customer-managed symmetric KMS key** for PHI data.
- [ ] Key policy: grant only the necessary IAM principals `kms:GenerateDataKey` and
  `kms:Decrypt`. Do not grant `kms:*` or use wildcards.
- [ ] Enable automatic key rotation; configure period (90–2560 days, default 365).
- [ ] Tag the key with data classification and owner.
- [ ] Store the CMK ARN in **SSM Parameter Store** as a plain `String` parameter
  (e.g., `/myapp/prod/phi-bucket-cmk-arn`). Do not store it in Secrets Manager.
- [ ] CloudWatch alarm on `kms:ScheduleKeyDeletion` and `kms:DisableKey` events for
  this key.
- [ ] Document on-demand rotation procedure for incident response (requires
  `kms:RotateKeyOnDemand`; max 25 uses per key).

### Bucket Creation
- [ ] Enable **versioning** before or at creation.
- [ ] If WORM is required, enable **Object Lock** at bucket creation time (cannot be
  added later) and set COMPLIANCE mode with an appropriate retention period.
- [ ] Set **Object Ownership to Bucket owner enforced** (disables ACLs).

### Bucket Encryption
- [ ] Set default encryption to **SSE-KMS** with the dedicated CMK.
- [ ] Enable **S3 Bucket Keys** to reduce KMS API call costs.

### Bucket Policy (apply all four layers)
- [ ] **Deny non-HTTPS:** Deny `s3:*` where `aws:SecureTransport` is false.
- [ ] **Enforce SSE-KMS:** Deny `s3:PutObject` unless
  `s3:x-amz-server-side-encryption` equals `aws:kms`.
- [ ] **Require specific CMK:** Deny `s3:PutObject` unless
  `s3:x-amz-server-side-encryption-aws-kms-key-id` matches the CMK ARN.
- [ ] **Restrict to VPC endpoint:** Deny access where `aws:sourceVpce` does not match
  the approved endpoint ID (for workloads inside a VPC).

### Block Public Access
- [ ] Enable all four BPA settings at the bucket level in addition to account level.

### Network Isolation
- [ ] Deploy a **VPC gateway endpoint** for S3 in every VPC that accesses PHI data.
- [ ] Route table updated to direct S3 traffic through the gateway endpoint.

### Logging
- [ ] **CloudTrail data events** capturing object-level operations (`GetObject`,
  `PutObject`, `DeleteObject`) for this bucket.
- [ ] **Server access logging** enabled (deliver to CloudWatch Logs for KMS encryption
  and cross-account aggregation support).
- [ ] Log retention period set to meet HIPAA requirements (recommend 6–7 years minimum
  consistent with HHS guidance).

### Monitoring and Detection
- [ ] AWS Config enabled; deploy the HIPAA conformance pack.
- [ ] AWS Security Hub enabled; review S3 controls S3.3, S3.8, S3.15, S3.17.
- [ ] CloudWatch alarms or EventBridge rules on `s3:DeleteBucket`,
  `s3:PutBucketPolicy` changes, and KMS key deletion/disabling.

### Operational
- [ ] IAM Access Analyzer for S3 enabled to detect unintended external access.
- [ ] Periodic (at minimum annual) review of bucket policy, KMS key policy, and
  CloudTrail findings as part of HIPAA risk analysis (§164.308(a)(1)(ii)(A)).
- [ ] Incident response runbook covers S3 PHI breach scenario (unauthorized access,
  accidental public exposure, CMK deletion).

---

*Sources used in this document:*

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerSideEncryptionCustomerKeys.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryptionInTransit.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/security_iam_service-with-iam.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/logging-with-S3.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudtrail-logging.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-compliance.html
- https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html
- https://docs.aws.amazon.com/kms/latest/developerguide/kms-cryptography.html
- https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html
- https://docs.aws.amazon.com/artifact/latest/ug/managing-agreements.html
- https://docs.aws.amazon.com/securityhub/latest/userguide/s3-controls.html
- https://docs.aws.amazon.com/config/latest/developerguide/operational-best-practices-for-hipaa_security.html
- https://aws.amazon.com/compliance/hipaa-eligible-services-reference/
- https://docs.aws.amazon.com/kms/latest/developerguide/rotating-keys-enable.html
- https://docs.aws.amazon.com/kms/latest/developerguide/rotate-keys.html
- https://docs.aws.amazon.com/kms/latest/developerguide/rotating-keys-on-demand.html
- https://docs.aws.amazon.com/prescriptive-guidance/latest/aws-kms-best-practices/data-protection-encryption.html
- https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/sec_protect_data_rest_key_mgmt.html
- https://docs.aws.amazon.com/solutions/latest/automated-security-response-on-aws/aws-systems-manager-parameter-store.html
