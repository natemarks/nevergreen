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
per the `ingress_cidr` setting in its config):

```bash
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text)
URL="http://$PUBLIC_IP:8188"
echo "$URL"
```

(`config/comfyui_client.py`, used in step 5 below via `make comfyui_prompt`,
runs this exact same lookup internally — no separate script needed there.)

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

Still inside the SSM session. Two example checkpoints — one for cartoon/anime
style (Character A's primary style per `human-workflow-steps.md`'s own
example prompt), one for realistic images (for later use). Both are
standard SDXL 1.0 checkpoints, well within the `g4dn.xlarge`/Tesla T4's
16GB VRAM (no instance upgrade needed for either). For this UAT, one is
enough to prove the pipeline end-to-end — download whichever you want to
test with, or both.

**Cartoon/anime — `cagliostrolab/animagine-xl-4.0`** (verified current: actively
maintained, explicitly documented as not an NSFW-focused model, unlike most
other top-ranked anime SDXL checkpoints in 2026):

```bash
sudo -u ubuntu /opt/comfyui/venv/bin/pip install huggingface_hub
sudo -u ubuntu /opt/comfyui/venv/bin/hf download \
  cagliostrolab/animagine-xl-4.0 \
  animagine-xl-4.0-opt.safetensors \
  --local-dir /opt/comfyui/models/checkpoints
```

**Realistic — `RunDiffusion/Juggernaut-XI-v11`** (the newest Juggernaut XL
release RunDiffusion hosts officially on HuggingFace; their newer "Ragnarok"
release is Civitai-only and would need Civitai token handling we don't have
yet):

```bash
sudo -u ubuntu /opt/comfyui/venv/bin/pip install huggingface_hub
sudo -u ubuntu /opt/comfyui/venv/bin/hf download \
  RunDiffusion/Juggernaut-XI-v11 \
  Juggernaut-XI-byRunDiffusion.safetensors \
  --local-dir /opt/comfyui/models/checkpoints
```

Confirm the `.safetensors` file(s) landed under
`/opt/comfyui/models/checkpoints/`.

## 5. Generate an image

From your laptop, run `config/comfyui_client.py` via its Make target. It
re-runs the same instance/URL discovery as step 2, **waits** for the port to
actually accept connections (useful right after a fresh instance launch —
`comfyui.service` takes a few minutes to come up), then POSTs your workflow,
wrapping it under `"prompt"` automatically — no more manual
`-d "{\"prompt\": $(cat workflow.json)}"` shell-escaping:

```bash
make comfyui_prompt app_env=dev workflow=workflows/txt2img-example.json
```

`workflows/txt2img-example.json` (checked into the repo) is a ComfyUI
**API-format** export — Workflow menu → **Export (API)** (not the plain
Export/Save, which produces a different, incompatible schema) — of the
graph built and tested in ComfyUI's UI first (checkpoint loader +
positive/negative `CLIPTextEncode` + `KSampler` + `VAEDecode` +
`SaveImage`), pointed at `Juggernaut-XI-byRunDiffusion.safetensors`. Edit
`ckpt_name` in it to point at a different downloaded checkpoint, or export
your own workflow to a new file under `workflows/`. Confirm a PNG appears
under `/opt/comfyui/output/` on the instance.

**Re-running it:** `KSampler`'s `seed` is a frozen number in the exported
file. `SaveImage` always writes a new file regardless (ComfyUI never skips
output/side-effect nodes even on a full cache hit), but the sampling pass
itself will be skipped as a no-op if every input — including that seed — is
identical to the last run. Edit the seed between runs if you want a genuinely
new image rather than a re-save of the cached one.

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
