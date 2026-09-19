# Conversation: Local LLM Image Generation Research

This document summarizes a research conversation exploring how to use local LLMs and diffusion models to generate cartoon character images, culminating in an AWS infrastructure design.

---

## Research Files Produced

| File | Contents |
|---|---|
| [local-llm-image-generation.md](./local-llm-image-generation.md) | Tool stack, all three use cases (evaluate/fix, prompt expansion, character consistency) |
| [two-stage-workflow.md](./two-stage-workflow.md) | Stage 1 vs Stage 2 infrastructure; text-only vs masking; ControlNet Tile; LLM role per stage |
| [human-workflow-steps.md](./human-workflow-steps.md) | Step-by-step human actions paired with tool mechanics for every step |
| [image-metadata.md](./image-metadata.md) | PNG metadata embedding, original prompt importance for inpainting, workflow changes for Stage 2 |
| [aws-infrastructure.md](./aws-infrastructure.md) | Phased AWS infrastructure design for the full cartoon character pipeline |

---

## Core Questions and Answers

### How do people use local LLMs to generate sophisticated images?

Three use cases in increasing complexity:

1. **Evaluate and fix:** Generate an image → vision LLM (LLaVA, Florence-2) evaluates it against the description → FaceDetailer auto-fixes faces → ClipSeg (`Mask by Text`) targets specific body regions for inpainting
2. **Prompt expansion:** LLM generates a JSON array of varied SD-style prompts from a seed → batch generate → pick favorite
3. **Character consistency:** IP-Adapter FaceID (zero training) or trained LoRA (Kohya_ss, 15–30 images) → consistent character across scenes

### What is the difference between exploration and refinement?

**Exploration (Stage 1)** diverges — one seed prompt fans out into many varied images. The LLM acts as a creative expander. Goal: find the best candidate.

**Refinement (Stage 2)** converges — one "close" image is improved surgically. The LLM acts as a targeted fix generator. Goal: resolve specific flaws without disturbing what's already good.

### What is the most effective path to a desired image?

1. Fan out first (Stage 1) to find the right composition and style cheaply
2. Upscale the winner with ControlNet Tile (denoise 0.3–0.5) — reveals flaws at higher resolution
3. Auto-fix faces with FaceDetailer (YOLO detection, fully automated)
4. Fix regions by text — type `"left hand"` into ClipSeg → mask generated automatically → inpaint with `[original prompt] + [fix suffix]`
5. Manual mask painting only when ClipSeg can't isolate the region

### Do people use only text prompts in Stage 2, or do they also paint masks?

Both — but painting is the fallback, not the default. Three levels of masking effort:

- **Automated:** FaceDetailer (faces, zero input)
- **Text-directed:** ClipSeg / `Mask by Text` (any describable region)
- **Manual painting:** ComfyUI MaskEditor or A1111 inpainting tab (irregular regions ClipSeg can't isolate)

Text-only img2img causes drift everywhere and is not suitable for localized fixes.

### Why does the original prompt matter for inpainting?

ComfyUI's `SaveImage` node automatically embeds the full generation graph as a `"workflow"` PNG tEXt chunk. If you inpaint with only a fix prompt, the model loses its style anchor and causes color/texture drift at mask boundaries. The correct conditioning is `[original prompt] + [fix suffix]`. In Stage 2, drag-and-drop the selected PNG onto the ComfyUI canvas to restore the full graph automatically.

### What workflows do the prototypes support across phases?

| Phase | Workflows | Human involvement |
|---|---|---|
| 0 | Explore-A (manual, single instance) | Every prompt, every image |
| 1 | Explore-A + Explore-B (automated, SQS worker) | Submit seed, review outputs, trigger refine manually |
| 2 | + Refine + Enhance (ECS, concurrent) | Submit seed, review, flag "close" images |
| 3 | + Auto-promotion + Model sync (Lambda scoring) | Submit seed, review final output only |

---

## Key Tool Stack

| Tool | Role |
|---|---|
| ComfyUI | Visual node-graph orchestrator for diffusion pipelines |
| Ollama | Local LLM server — prompt expansion, image evaluation |
| Plush for ComfyUI (APE node) | Wires Ollama into ComfyUI graph via `/v1/chat/completions` |
| IP-Adapter FaceID (`ip-adapter-faceid-plusv2`) | Character consistency from a reference image, zero training |
| ControlNet + comfyui_controlnet_aux | Pose/depth/tile conditioning; TilePreprocessor for upscale |
| ComfyUI-Impact-Pack (FaceDetailer) | YOLO face detection → automated inpaint → paste back |
| Masquerade Nodes (`Mask by Text`) | ClipSeg text-to-mask for targeted inpainting |
| Florence-2 / LLaVA | Vision LLMs for image evaluation against description |
| Kohya_ss | Character LoRA training (15–30 images, 30–90 min) |

---

## AWS Infrastructure Summary

Full details in [aws-infrastructure.md](./aws-infrastructure.md).

**Instance recommendations:**
- `g4dn.xlarge` (T4 16GB, ~$0.35–0.50/hr spot) — SDXL exploration, Character A
- `g5.xlarge` (A10G 24GB, ~$0.54/hr spot) — Flux or Character B with IP-Adapter
- `g5.2xlarge` (A10G 24GB, ~$0.65/hr spot) — refinement passes

**Queue topology (4 SQS queues):**
- `explore-a-queue` — Character A, prompts only
- `explore-b-queue` — Character B, prompt + reference image S3 key
- `refine-queue` — "close" images promoted from explore queues
- `enhance-queue` — targeted inpainting sub-jobs

**Architecture:** SQS → ECS worker (EC2 launch type, GPU AMI) → ComfyUI API → S3 output → Lambda scoring → next queue. No Step Functions, no API Gateway, no Fargate.

**One ComfyUI `.json` workflow file per queue.** The queue determines the workflow — no runtime branching in the worker.

**Simplification principle:** Many small, targeted workflows rather than few complex flexible ones. Each queue = one instance type = one workflow file = one ECS task definition.
