# AWS Infrastructure for Cartoon Character Image Generation

Research compiled from primary AWS sources and community documentation.  
Design goal: many small, targeted workflows; prototype-first; cartoon character generation.

---

## Goal Recap

Two character types:
- **Character A** — exploratory prompts only (LLM expansion → batch generation → pick winner)
- **Character B** — prompt + reference image (same, but adds IP-Adapter FaceID conditioning)

Two pipeline stages:
- **Stage 1 (Explore):** LLM expands seed → batch generate → score → "close" images promoted
- **Stage 2 (Refine):** upscale → face-fix → targeted inpainting → final image to S3

---

## Instance Selection

### VRAM Requirements

| Model | Min VRAM | Notes |
|---|---|---|
| SDXL (juggernautXL, realvisxl) | 10–12 GB | 1024×1024 generation |
| SDXL + IP-Adapter FaceID | 12–14 GB | Character B adds ~2GB overhead |
| Flux.1-dev | 16–24 GB | Higher quality, much more VRAM |

### Recommended Instances

| Instance | GPU | VRAM | vCPUs | RAM | On-Demand | Spot (approx) | Use |
|---|---|---|---|---|---|---|---|
| **g4dn.xlarge** | NVIDIA T4 | 16 GB | 4 | 16 GB | $0.526/hr | ~$0.35–0.50/hr | SDXL prototype, Character A |
| **g5.xlarge** | NVIDIA A10G | 24 GB | 4 | 16 GB | $1.006/hr | ~$0.54/hr | Flux or Character B w/ IP-Adapter |
| **g5.2xlarge** | NVIDIA A10G | 24 GB | 8 | 32 GB | $1.212/hr | ~$0.65/hr | Refinement (more RAM for concurrent inpaint passes) |

**Recommendation:** Start with `g4dn.xlarge` for prototype (cheapest that fits SDXL). Upgrade to `g5.xlarge` if using Flux or Character B with IP-Adapter.  
Sources: [G4dn specs](https://docs.aws.amazon.com/ec2/latest/instancetypes/full.html), [G5 specs](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html), pricing via [instances.vantage.sh](https://instances.vantage.sh/)

**Use Spot for Explore stage** (batch, fault-tolerant — a spot interruption just requeuues the job).  
**Use On-Demand for Refine stage** (you don't want to lose a half-finished refinement run).

---

## Queue Topology (Simple)

Four SQS queues. Each maps to exactly one workflow type.

```
explore-a-queue      → Character A exploration jobs (prompts only)
explore-b-queue      → Character B exploration jobs (prompt + reference image S3 key)
refine-queue         → Refinement jobs for "close" images promoted from either explore queue
enhance-queue        → Optional: targeted enhancement passes (inpainting sub-jobs)
```

**Why four queues instead of one:** Each queue has a different worker type, scaling target, and spot/on-demand split. A single queue with a "type" field forces workers to filter — wasted polling and mismatched instance types.

**Do not use Step Functions.** SQS → worker → S3 → Lambda → next queue is simpler, cheaper, and easier to debug. Step Functions adds significant complexity for a workflow that is already naturally staged by queues.

---

## Phase 0 — Prototype (deploy in ~1 hour)

**Goal:** Get ComfyUI running on one GPU instance, callable via its REST API, outputting images to S3.

### Steps

1. **Launch g4dn.xlarge** with Deep Learning AMI (Ubuntu 22.04):
   ```bash
   # Get latest DLAMI AMI ID
   aws ssm get-parameters \
     --names /aws/service/deeplearning/ami/x86_64/pytorch-2.4-gpu-py310-ubuntu22.04/latest/image-id \
     --region us-east-1
   ```
   The Deep Learning AMI includes NVIDIA drivers, CUDA, and PyTorch pre-installed.  
   Source: [DLAMI GPU PyTorch 2.4](https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-ami-gpu-pytorch-2.4-ubuntu-22-04.html)

2. **Security group:** allow your IP on port 8188 (ComfyUI) and 11434 (Ollama). No public 0.0.0.0 exposure.

3. **Install ComfyUI** on the instance:
   ```bash
   git clone https://github.com/comfyanonymous/ComfyUI
   cd ComfyUI && pip install -r requirements.txt
   # Install custom nodes: Impact Pack, IPAdapter Plus, ControlNet Aux, Plush, Masquerade Nodes
   cd custom_nodes
   git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack
   git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
   git clone https://github.com/Fannovel16/comfyui_controlnet_aux
   git clone https://github.com/glibsonoran/Plush-for-ComfyUI
   git clone https://github.com/BadCafeCode/masquerade-nodes-comfyui
   ```

4. **Start ComfyUI** with the API enabled:
   ```bash
   python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header
   ```

5. **Create S3 bucket** for outputs:
   ```bash
   aws s3 mb s3://cartoon-images-output
   aws s3 mb s3://cartoon-models          # for Phase 1 model storage
   ```

6. **Test the API** by POSTing a workflow JSON to `http://<instance-ip>:8188/prompt`

**Phase 0 deliverable:** You can send a ComfyUI workflow JSON via curl and get an image back. Models are downloaded manually to the instance.

---

## Phase 1 — Automated Single Worker

**Goal:** Add a queue and a worker script. Images go from prompt → SQS → worker → ComfyUI API → S3.

### Components Added

**SQS Queue (`explore-a-queue`):**
- Standard queue (not FIFO — order doesn't matter for exploration)
- Visibility timeout: 900 seconds (15 min, enough for a full batch generation run)
- Dead-letter queue after 3 failures

**Worker Script (runs on the same EC2 instance, or as a simple cron/systemd service):**
```python
# Pseudocode
while True:
    msg = sqs.receive_message(QueueUrl=explore_a_queue, WaitTimeSeconds=20)
    if not msg: continue
    job = json.loads(msg['Body'])        # {seed_prompt, batch_size, character_type}
    
    # Call Ollama to expand prompt
    prompts = ollama_expand(job['seed_prompt'], n=job['batch_size'])
    
    # Submit each to ComfyUI API
    image_paths = []
    for prompt in prompts:
        image = comfyui_generate(prompt)
        key = f"explore/{job['job_id']}/{uuid4()}.png"
        s3.put_object(Bucket='cartoon-images-output', Key=key, Body=image)
        image_paths.append(key)
    
    sqs.delete_message(...)              # only after all images written
```

**Model files from S3:** Add to EC2 user data:
```bash
# Pull models from S3 at startup (run once, ~5-15 min for large checkpoints)
aws s3 sync s3://cartoon-models/checkpoints /home/ubuntu/ComfyUI/models/checkpoints
aws s3 sync s3://cartoon-models/loras /home/ubuntu/ComfyUI/models/loras
aws s3 sync s3://cartoon-models/controlnet /home/ubuntu/ComfyUI/models/controlnet
aws s3 sync s3://cartoon-models/ip-adapter /home/ubuntu/ComfyUI/models/ip-adapter
```
Source: [aws s3 sync docs](https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html)

**S3 event → notification (for Character B input images):**
When a reference image is uploaded to `s3://cartoon-images-output/reference/`, trigger a Lambda that puts a job on `explore-b-queue` with the S3 key included.  
Source: [S3 event notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/how-to-enable-disable-notification-intro.html)

**Phase 1 deliverable:** Drop a job on the queue, images appear in S3 automatically.

---

## Phase 2 — Concurrent Jobs with ECS

**Goal:** Scale to N concurrent workers, one ECS task per GPU instance, auto-scaled by queue depth.

### ECS Cluster Setup

ECS GPU workloads require **EC2 launch type** (Fargate does not support GPU).  
Source: [ECS GPU task definitions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html)

**Get the ECS GPU-optimized AMI:**
```bash
aws ssm get-parameters \
  --names /aws/service/ecs/optimized-ami/amazon-linux-2/gpu/recommended \
  --region us-east-1
```

**Launch template user data** (registers with ECS cluster and enables GPU):
```bash
#!/bin/bash
echo ECS_CLUSTER=cartoon-gen-cluster >> /etc/ecs/ecs.config
echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config
# Pull models from S3 at startup
aws s3 sync s3://cartoon-models /home/ec2-user/models
```
Source: [Launch GPU container instance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gpu-launch.html)

**ECS Task Definition** (one per workflow type):
```json
{
  "family": "explore-a-worker",
  "requiresCompatibilities": ["EC2"],
  "containerDefinitions": [{
    "name": "worker",
    "image": "your-ecr-account.dkr.ecr.us-east-1.amazonaws.com/comfyui-worker:latest",
    "resourceRequirements": [{
      "type": "GPU",
      "value": "1"
    }],
    "environment": [
      {"name": "QUEUE_URL", "value": "https://sqs.us-east-1.amazonaws.com/.../explore-a-queue"},
      {"name": "OUTPUT_BUCKET", "value": "cartoon-images-output"}
    ]
  }]
}
```

### Auto-Scaling by Queue Depth

Scale ECS services on **backlog per task** (not raw queue depth):  
`backlog_per_task = ApproximateNumberOfMessagesVisible / RunningTaskCount`

Set target: for a job that takes 5 minutes (300s) and acceptable latency of 10 min (600s), target = 600/300 = 2 messages per task.

```bash
# Application Auto Scaling target tracking policy
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id service/cartoon-gen-cluster/explore-a-service \
  --scalable-dimension ecs:service:DesiredCount \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 2.0,
    "CustomizedMetricSpecification": {
      "Metrics": [
        {"Label": "QueueDepth", "Id": "m1", "MetricStat": {"Metric": {"Namespace": "AWS/SQS", "MetricName": "ApproximateNumberOfMessagesVisible", "Dimensions": [{"Name": "QueueName", "Value": "explore-a-queue"}]}, "Stat": "Sum"}},
        {"Label": "RunningTasks", "Id": "m2", "MetricStat": {"Metric": {"Namespace": "ECS/ContainerInsights", "MetricName": "RunningTaskCount", "Dimensions": [{"Name": "ServiceName", "Value": "explore-a-service"}]}, "Stat": "Average"}},
        {"Label": "BacklogPerTask", "Id": "e1", "Expression": "m1 / m2", "ReturnData": true}
      ]
    }
  }'
```
Source: [Scale ECS based on SQS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-autoscaling-queue.html)

**Important:** Enable **scale-in protection** on ECS tasks while they're processing a message. Workers should set `SetInstanceProtection` before polling, clear it after deleting the SQS message. This prevents an instance from being terminated mid-generation.

### ECS Services (one per queue)

| ECS Service | Queue | Instance Type | Spot? | Min tasks | Max tasks |
|---|---|---|---|---|---|
| `explore-a-service` | `explore-a-queue` | g4dn.xlarge | Yes | 0 | 10 |
| `explore-b-service` | `explore-b-queue` | g5.xlarge | Yes | 0 | 5 |
| `refine-service` | `refine-queue` | g5.2xlarge | No | 0 | 3 |
| `enhance-service` | `enhance-queue` | g4dn.xlarge | No | 0 | 5 |

Min=0 means cluster scales to zero when all queues are empty (no idle GPU costs).

**Phase 2 deliverable:** Multiple concurrent jobs, auto-scaling, zero cost when idle.

---

## Phase 3 — Full Pipeline

### "Close Image" Promotion

When Stage 1 generates images, they land in `s3://cartoon-images-output/explore/{job_id}/`.

A **Lambda function** triggered by S3 `ObjectCreated` events:
1. Reads the PNG metadata (`PIL.Image.info["prompt"]` — ComfyUI embeds full workflow JSON automatically in every `SaveImage` output)
2. Calls a vision model (Ollama llama3.2-vision via API, or Amazon Rekognition for simpler scoring) to score the image against the seed description
3. If score ≥ threshold: puts a refinement job on `refine-queue` with the S3 key + original metadata
4. Writes score to a DynamoDB table for the human review UI

```python
# Lambda pseudocode
def handler(event, context):
    key = event['Records'][0]['s3']['object']['key']
    img_bytes = s3.get_object(Bucket=OUTPUT_BUCKET, Key=key)['Body'].read()
    
    # Extract original prompt from PNG metadata
    from PIL import Image
    import io, json
    img = Image.open(io.BytesIO(img_bytes))
    workflow = json.loads(img.info.get("prompt", "{}"))
    original_prompt = extract_clip_text(workflow)   # parse CLIPTextEncode nodes
    
    # Score image (Ollama vision or Rekognition)
    score = score_image(img_bytes, original_prompt)
    
    if score >= PROMOTE_THRESHOLD:
        sqs.send_message(
            QueueUrl=REFINE_QUEUE_URL,
            MessageBody=json.dumps({
                "source_key": key,
                "original_prompt": original_prompt,
                "score": score
            })
        )
```

Source: [S3 event notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-event-notifications.html), [PNG metadata from prior research](./image-metadata.md)

### Model Download Automation

**Pattern:** EC2 Spot instance (g4dn.xlarge or cheaper CPU instance) triggered by EventBridge scheduled rule or manually.

```
EventBridge rule (weekly cron) → Lambda → launch Spot EC2 instance with user data:
  - pip install huggingface_hub
  - huggingface-cli download <model-id> --local-dir /tmp/models/
  - aws s3 sync /tmp/models/ s3://cartoon-models/<model-id>/
  - instance self-terminates
```

**Why not Lambda directly:** Lambda has a 15-minute max execution time and 512MB ephemeral storage (expandable to 10GB, but model files can be 5–20GB). A short-lived EC2 Spot instance with instance storage handles large model files cleanly.

**Alternative for smaller models (LoRAs, ControlNet models < 2GB):** Lambda with `/tmp` expanded to 10GB + streaming download directly to S3 multipart upload. No EC2 needed.

### Character A vs Character B Job Routing

Jobs are distinguished by payload type, not a single shared queue:

```
Human submits Character A job:
  → PUT to explore-a-queue: { seed_prompt, batch_size }
  → Workers use: CLIPTextEncode + KSampler only (no reference image)

Human submits Character B job:
  → Upload reference image to s3://cartoon-images-output/reference/
  → S3 event → Lambda → PUT to explore-b-queue: { seed_prompt, batch_size, reference_key }
  → Workers use: CLIPTextEncode + IP-Adapter FaceID + KSampler
```

**Phase 3 deliverable:** End-to-end automated pipeline. Human submits a seed prompt, "close" images auto-promote to refinement, final images land in S3.

---

## Simplification Recommendations

### What to Avoid

| Service | Why Skip |
|---|---|
| **AWS Step Functions** | Adds orchestration complexity; SQS → Lambda → SQS achieves the same staged pipeline with less code and easier debugging |
| **API Gateway** | No public API needed; workers poll SQS directly; Lambda is invoked by S3 events or EventBridge |
| **Amazon Rekognition** | Too generic for cartoon art scoring; a small vision LLM (llama3.2-vision via Ollama) evaluates against your specific description far better |
| **ECR Public gallery models** | ComfyUI with custom nodes is not a good Docker image citizen; the custom node ecosystem changes fast. Run ComfyUI directly on the instance, not in a container, at least for the prototype phases. |
| **Fargate for GPU** | Fargate does not support GPU ([confirmed in ECS docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html)). EC2 launch type only. |
| **ALB/ELB** | Workers pull from SQS; no inbound HTTP routing needed. ComfyUI's REST API is called from within the same instance. |

### Keep ComfyUI Workflows Small and Targeted

One ComfyUI `.json` workflow file per job type. Do not build one mega-workflow with conditional branches:

| Workflow file | Does exactly one thing |
|---|---|
| `explore-a.json` | Prompt expansion + SDXL batch generation, Character A |
| `explore-b.json` | Same + IP-Adapter FaceID conditioning, Character B |
| `upscale-tile.json` | ControlNet Tile 2× upscale only |
| `face-detail.json` | FaceDetailer only |
| `inpaint-region.json` | ClipSeg mask + inpainting KSampler |

The worker knows which workflow to load based on which SQS queue it's consuming from. Job type = queue = workflow file = instance type. No runtime branching.

### Recommended S3 Bucket Structure

```
s3://cartoon-models/
  checkpoints/          # SDXL base models (juggernautXL, etc.)
  loras/                # Character LoRAs
  controlnet/           # ControlNet models (tile, openpose, etc.)
  ip-adapter/           # IP-Adapter FaceID weights

s3://cartoon-images-output/
  explore/{job_id}/     # Stage 1 batch output (raw exploration images)
  reference/            # Character B origin images (human-uploaded)
  refine/{job_id}/      # Stage 2 refined outputs
  final/                # Human-approved finals
```

S3 lifecycle: move `explore/` to S3 Intelligent-Tiering after 30 days (most exploration images are throwaways).

---

## Quick Start Sequence (Fastest to First Image)

1. `aws ec2 run-instances` with `g4dn.xlarge` + DLAMI Ubuntu 22.04 — ~5 minutes
2. SSH in, install ComfyUI + custom nodes — ~20 minutes
3. Download SDXL checkpoint to instance — ~10 minutes (juggernautXL, ~6GB)
4. `python main.py --listen 0.0.0.0` — running in 30 seconds
5. POST a workflow JSON to port 8188 — first image in ~60 seconds (SDXL, 20 steps, T4)

**Total time to first image: ~40 minutes.** Everything else (SQS, ECS, Lambda) is Phase 1+.

---

## Sources

- [ECS GPU task definitions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html)
- [Launch GPU container instance for ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gpu-launch.html)
- [Scale ECS services based on SQS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-autoscaling-queue.html)
- [EC2 accelerated computing instance types](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html)
- [G4dn instance family](https://docs.aws.amazon.com/ec2/latest/instancetypes/full.html)
- [Deep Learning AMI GPU PyTorch 2.4](https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-ami-gpu-pytorch-2.4-ubuntu-22-04.html)
- [S3 event notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/how-to-enable-disable-notification-intro.html)
- [SQS scaling policy for EC2 Auto Scaling](https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-using-sqs-queue.html)
- [Deploy ComfyUI on AWS elastically](https://aws.amazon.com/blogs/architecture/deploy-stable-diffusion-comfyui-on-aws-elastically-and-efficiently/) — AWS Architecture Blog
- Instance pricing: [instances.vantage.sh](https://instances.vantage.sh/)
- Prior workflow research: [local-llm-image-generation.md](./local-llm-image-generation.md), [two-stage-workflow.md](./two-stage-workflow.md), [image-metadata.md](./image-metadata.md)
