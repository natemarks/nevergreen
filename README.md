# Nevergreen — Cartoon Character Image Generation

An AWS CDK (Python) app that deploys a ComfyUI-based pipeline for generating
cartoon/anime and realistic character images. See
[research/aws-infrastructure.md](research/aws-infrastructure.md) for the full
phased design, and [CLAUDE.md](CLAUDE.md) for the registry/discovery/pipeline
conventions this project follows.

## Phase 0: ComfyUI prototype instance

Phase 0 stands up a single GPU instance running ComfyUI, driven manually
through its own web UI or the API — no custom UI, no automation of the
generation pipeline itself yet (that starts in later phases).

**What it deploys** (`dev` environment only):
- `comfyui` — a `g4dn.xlarge` (Tesla T4, 16GB VRAM) instance on a Deep
  Learning AMI, running ComfyUI + custom nodes (Impact Pack, IPAdapter Plus,
  ControlNet Aux, Plush, Masquerade Nodes) as a `comfyui.service` systemd
  unit, reachable via a public IP (locked to one configured CIDR) or SSM
  Session Manager.
- `nevergreen-dev-models` / `nevergreen-dev-images` — S3 buckets for model
  checkpoints and generated images.

**Verified example checkpoints** (both standard SDXL 1.0 — no instance
upgrade needed for either):
- Cartoon/anime: [`cagliostrolab/animagine-xl-4.0`](https://huggingface.co/cagliostrolab/animagine-xl-4.0) (file `animagine-xl-4.0-opt.safetensors`)
- Realistic: [`RunDiffusion/Juggernaut-XI-v11`](https://huggingface.co/RunDiffusion/Juggernaut-XI-v11) (file `Juggernaut-XI-byRunDiffusion.safetensors`)

## Phase 1: automated single worker consumes queue jobs

Phase 1 adds `explore-a-queue` (standard SQS, 900s visibility timeout, DLQ
after 3 failed receives) and an `explore-worker.service` systemd unit on the
same Phase 0 instance. Dropping a job on the queue drives the full pipeline
with no manual ComfyUI interaction: SQS poll → Ollama prompt-expansion (one
seed prompt becomes `batch_size` varied prompts) → one ComfyUI generation per
expanded prompt → S3 upload → delete message. Character A only.

**What it adds** (`dev` environment only):
- `nevergreen-dev-explore-a-queue` (+ its `-dlq`) — the job queue.
- `explore-worker.service` — polls the queue, writes generated images to
  `s3://nevergreen-dev-images/explore/{job_id}/`.
- Ollama, installed on the same instance for prompt expansion, with its
  `llama3.1` model synced from the models bucket at boot (not pulled live
  from Ollama's own registry — see `make sync_models` below).

## Prerequisites

- AWS credentials for the target environment's account.
- `aws` CLI v2 and `session-manager-plugin` (for `aws ssm start-session`).
- `make .venv && make node_modules` (or the CI bypass in
  [CLAUDE.md](CLAUDE.md#pipeline) if `pyenv` isn't available).
- [Ollama installed locally](https://ollama.com/download) — only needed to
  run `make sync_models` (it pulls the LLM on your machine, not any AWS
  instance, before syncing it to S3).

## Deploy

```bash
make discover app_env=dev          # resolves the real Deep Learning AMI id
make cdk-diff-all app_env=dev      # review before approving
make cdk-deploy-all app_env=dev
```

## Test it (UAT)

This is the acceptance test for Phase 0 — an end-to-end proof that a prompt
turns into an image landing in S3. `make comfyui_prompt` is the final test
automation for this: it discovers the current instance's URL on its own
(no separate lookup step needed), waits for the port to actually accept
connections (useful right after a fresh launch — `comfyui.service` takes a
few minutes to come up), and POSTs a workflow, wrapped correctly under
`"prompt"`:

```bash
make comfyui_prompt app_env=dev workflow=workflows/txt2img-example.json
```

Confirm a new PNG appears under `/opt/comfyui/output/` on the instance, then
push it to S3 and confirm it landed (the instance role already has the
images bucket's read-write policy attached):

```bash
aws s3 cp /opt/comfyui/output/<file>.png s3://nevergreen-dev-images/explore/manual-uat/
aws s3 ls s3://nevergreen-dev-images/explore/manual-uat/
```

**No new PNG on a repeat run isn't necessarily a failure:** `KSampler`'s
`seed` is frozen in the exported workflow file. `SaveImage` always writes a
new file regardless, but the sampling pass itself is a no-op cache hit if
every input, including that seed, is unchanged from the previous run — edit
the seed in `workflows/txt2img-example.json` between runs for a genuinely
new image.

### Troubleshooting if `make comfyui_prompt` fails

1. **Find the instance and confirm ComfyUI is actually running** — SSM in
   and check the service:
   ```bash
   bash scripts/list_instances.sh   # get the instance id
   aws ssm start-session --target <instance-id>
   sudo systemctl status comfyui.service
   sudo journalctl -u comfyui.service -n 100 --no-pager
   ```
   If it isn't `active (running)`, the userdata install
   (`stack/simple_asg/userdata_gpu_worker.sh`) is best-effort — a custom
   node's `requirements.txt` pulling a CPU-only `torch` build is the most
   likely failure, fixable with a manual `pip install` of the matching CUDA
   wheel over this same session.
2. **A `node_errors` response, a missing-checkpoint error, or an Ollama
   `404` on `/api/chat` usually means the models bucket is missing
   content.** `make sync_models` (`config/model_manifest.json` lists both
   sections) runs entirely locally — no GPU instance needed just to sync
   model content:
   - `checkpoints`: downloads each from Hugging Face, uploads to
     `s3://nevergreen-dev-models/checkpoints/` (add a `HF_TOKEN=...` line
     to a gitignored `.env` if a listed repo is gated). Skips the
     download/upload entirely for a checkpoint already in the bucket —
     these are multi-GB files, so this matters; delete the S3 object
     first to force a re-sync.
   - `ollama_models`: runs `ollama pull <model>` **on your own machine**
     (requires Ollama installed locally), then `aws s3 sync`s your local
     `~/.ollama/models` to `s3://nevergreen-dev-models/ollama/`.
   ```bash
   make sync_models app_env=dev
   ```
   Every instance boot (`userdata_gpu_worker.sh`) runs `aws s3 sync` from
   both of those bucket prefixes — into `/opt/comfyui/models/checkpoints/`
   and `/usr/share/ollama/.ollama/models/` respectively — instead of
   downloading checkpoints from Hugging Face or pulling the LLM from
   Ollama's own registry live at boot. The bucket's own listing is the
   source of truth for both, so a fresh or relaunched instance is always
   self-sufficient once the bucket has what it needs; there's no separate
   manifest to keep in sync. If content is already in the bucket but
   still missing on a *running* instance, terminate it (the ASG relaunches
   with the current userdata) rather than syncing by hand.
3. **If you want a different workflow than the checked-in example** (a
   different checkpoint, prompt, or resolution), build one in ComfyUI's web
   UI (Load Checkpoint → positive/negative CLIP Text Encode → KSampler →
   VAE Decode → Save Image), test it with Queue Prompt, then export via
   **Workflow → Export (API)** (not the plain Export/Save, which produces
   an incompatible schema) to a new file under `workflows/`.

## Test Phase 1 (UAT)

This is the acceptance test for Phase 1 — dropping a job on
`explore-a-queue` and confirming images land in S3 automatically. `make
queue_job` resolves the queue's real URL and sends the job in one step:

```bash
make queue_job app_env=dev seed_prompt="a fox exploring a neon city" batch_size=3
```

It prints the `job_id` it generated and the exact S3 path to check next
(`s3://nevergreen-dev-images/explore/<job_id>/`). (Equivalent by hand:
`aws sqs get-queue-url --queue-name nevergreen-dev-explore-a-queue` then
`aws sqs send-message --queue-url <url> --message-body '{"seed_prompt":
"...", "batch_size": 3}'` — with a hand-picked `job_id` in the body, since
nothing will print one for you.)

Wait a few minutes (Ollama's prompt expansion + 3 ComfyUI generations), then
confirm the images appeared under that same path — not a plain listing of
everything under `explore/`, which mixes in every other job's output too:

```bash
aws s3 ls s3://nevergreen-dev-images/explore/<job_id>/ --recursive
```

If nothing appears, SSM into the instance and check both services — the
worker depends on Ollama and ComfyUI already being up (`After`/`Wants` in
its systemd unit only orders startup, it doesn't retry a dependency that's
still failing):

```bash
sudo systemctl status explore-worker.service ollama.service comfyui.service
sudo journalctl -u explore-worker.service -n 100 --no-pager
```

A message that keeps reappearing on the queue after ~15 minutes (its
visibility timeout) instead of being deleted means the worker is failing on
it — check the log above for the exception; after 3 failed receives it moves
to `nevergreen-dev-explore-a-queue-dlq`.

## Cost control

GPU instances aren't cheap idle. `cdk deploy` alone does **not** restore
Auto Scaling capacity after a manual scale-down (CloudFormation only pushes
property changes relative to the previously deployed template, not live AWS
state) — use these instead:

```bash
make asg_down app_env=dev   # scale every simple_asg ASG to 0
make asg_up app_env=dev     # restore min/max from config; ASG relaunches
```

## Known gotchas

- ComfyUI's server is plain HTTP — no TLS certificate is configured.
- The GPU worker's root device name must match the AMI's actual
  `RootDeviceName` (currently `/dev/sda1` for this Deep Learning AMI, not the
  more common `/dev/xvda`) — otherwise the configured EBS volume attaches as
  an idle second disk instead of becoming the root filesystem, and the OS
  keeps whatever tiny size the AMI's own snapshot shipped with.
- A fresh instance gets a new public IP on every launch — re-run
  `bash scripts/list_instances.sh` or `make comfyui_prompt` (which
  re-discovers it every time) rather than reusing a stale IP.

## Testing this project's own code

Golden-file tests compare synthesized CloudFormation templates against
checked-in expected output — a mismatch means an unintended template
change. See [CLAUDE.md](CLAUDE.md#golden-files) for the full convention.

```bash
make static        # shellcheck, black, mypy, pylint, unit tests
make unit-update_golden   # regenerate golden files after an intentional change
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
