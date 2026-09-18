# Phase 0 UAT — ComfyUI prototype instance

Manual acceptance steps for [Phase 0: ComfyUI prototype instance deployed
and reachable](https://github.com/natemarks/nevergreen/issues/27). Run these
against the `dev` environment. When every step below is confirmed, post the
result as a comment on that issue — the ticket closes on that confirmation,
which also unblocks
[Phase 1](https://github.com/natemarks/nevergreen/issues/28).

## Prerequisites

- AWS credentials for the `dev` account (709310380790), region `us-east-1`.
- `aws` CLI v2, `session-manager-plugin` installed (for `aws ssm
  start-session`).
- Repo virtualenv active: `source .venv/bin/activate`.

## 1. Discover, diff, deploy

```bash
make discover app_env=dev
make cdk-diff-all app_env=dev      # review before approving
make cdk-deploy-all app_env=dev
```

`make discover` resolves the real Deep Learning AMI id (the checked-in config
has a placeholder `ami-00000000000000000` — deploy will fail if you skip
this step). Confirm the diff shows the three new stacks (`SimpleS3Models`,
`SimpleS3Images`, `SimpleAsgComfyui`) with no changes to existing stacks
(`AppVpc`, `SimpleAsgAaa`, `SecureS3Phi`).

## 2. Find the instance and its URL

Get the instance id (needed later for the SSM Session Manager step):

```bash
ASG_NAME=$(aws cloudformation describe-stack-resources \
  --stack-name NevergreenDevSimpleAsgComfyuiStack \
  --query "StackResources[?ResourceType=='AWS::AutoScaling::AutoScalingGroup'].PhysicalResourceId" \
  --output text)
INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names "$ASG_NAME" \
  --query "AutoScalingGroups[0].Instances[0].InstanceId" --output text)
echo "$INSTANCE_ID"
```

Get the URL to test directly against ComfyUI (the `comfyui` instance is in
a public subnet with a public IP specifically so you can reach it this way,
per the `ingress_cidr` setting in its config). `scripts/comfyui_url.sh` runs
the same lookup plus the public-IP query and just prints the URL:

```bash
URL=$(scripts/comfyui_url.sh)
echo "$URL"
```

## 3. Confirm ComfyUI is running

Two ways in — either is fine for UAT:

**a) Direct browser/curl** (works only from `73.126.140.136`, the CIDR
configured on this instance):

```bash
curl -sf "$URL/system_stats" | head -c 200
```

**b) SSM Session Manager** (works from anywhere with AWS credentials, no
public IP needed):

```bash
aws ssm start-session --target "$INSTANCE_ID"
# on the instance:
sudo systemctl status comfyui.service
sudo journalctl -u comfyui.service -n 100 --no-pager
```

If `comfyui.service` isn't `active (running)`, check the journal — the
userdata script (`stack/simple_asg/userdata_gpu_worker.sh`) is a best-effort
install; a custom node's `requirements.txt` pulling a CPU-only `torch` build
is the most likely failure and needs a manual `pip install` fix with the
correct CUDA wheel over this same SSM session.

## 4. Download a checkpoint (manual — Phase 0 has no automated model sync)

Still inside the SSM session:

```bash
sudo -u ubuntu /opt/comfyui/venv/bin/pip install huggingface_hub
sudo -u ubuntu /opt/comfyui/venv/bin/huggingface-cli download \
  <model-repo, e.g. RunDiffusion/Juggernaut-XL-v9> \
  --local-dir /opt/comfyui/models/checkpoints
```

Confirm the `.safetensors` file landed under
`/opt/comfyui/models/checkpoints/`.

## 5. Generate an image

From your laptop (if using the direct path) or from within the SSM session
(`curl localhost:8188/...`):

```bash
curl -s -X POST "$URL/prompt" \
  -H "Content-Type: application/json" \
  -d @workflow.json
```

`workflow.json` is a ComfyUI API-format workflow graph (checkpoint loader +
positive/negative `CLIPTextEncode` + `KSampler` + `VAEDecode` + `SaveImage`) —
export one from ComfyUI's own UI ("Save (API Format)") pointed at the
checkpoint you just downloaded. Confirm a PNG appears under
`/opt/comfyui/output/` on the instance.

## 6. Push the image to S3 and confirm it landed

Still on the instance (the `comfyui` instance role already has the images
bucket's read-write managed policy attached — see [Decide S3 bucket stack
tier](https://github.com/natemarks/nevergreen/issues/25)):

```bash
aws s3 cp /opt/comfyui/output/<generated-file>.png \
  s3://nevergreen-dev-images/explore/manual-uat/
aws s3 ls s3://nevergreen-dev-images/explore/manual-uat/
```

Confirm the object is listed.

## 7. Report the result

Post a comment on [Phase 0's
ticket](https://github.com/natemarks/nevergreen/issues/27) confirming:
- the instance deployed and `comfyui.service` is running,
- a checkpoint was downloaded,
- a workflow POST returned an image, and
- that image is confirmed in `s3://nevergreen-dev-images/explore/manual-uat/`.

That confirmation is what closes the ticket and unblocks Phase 1.
