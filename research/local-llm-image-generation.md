# Local LLM + Stable Diffusion: Sophisticated Image Generation Workflows

Research compiled from primary sources (GitHub READMEs, official docs). All claims cite their source.

---

## Core Tool Stack

| Tool | Role | Source |
|------|------|--------|
| **ComfyUI** | Visual node-graph orchestrator for diffusion pipelines | [github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI) |
| **Ollama** | Local LLM server (REST API, vision model support) | [github.com/ollama/ollama](https://github.com/ollama/ollama) |
| **IP-Adapter** | Reference-image conditioning (22M params, preserves appearance/face) | [github.com/tencent-ailab/IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) |
| **ComfyUI_IPAdapter_plus** | ComfyUI nodes for IP-Adapter and FaceID models | [github.com/cubiq/ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) |
| **ComfyUI-Impact-Pack** | Face detection, FaceDetailer, SEGS-based region enhancement | [github.com/ltdrdata/ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) |
| **ControlNet v1.1** | Conditioning by pose/depth/edge/segmentation | [github.com/lllyasviel/ControlNet-v1-1-nightly](https://github.com/lllyasviel/ControlNet-v1-1-nightly) |
| **comfyui_controlnet_aux** | Preprocessor nodes (DWPose, Depth Anything, AIO) | [github.com/Fannovel16/comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) |
| **Plush for ComfyUI** | LLM-powered prompt expansion/refinement nodes | [github.com/glibsonoran/Plush-for-ComfyUI](https://github.com/glibsonoran/Plush-for-ComfyUI) |
| **ComfyUI-Florence2** | Florence-2 vision model: captioning, object detection, VQA | [github.com/kijai/ComfyUI-Florence2](https://github.com/kijai/ComfyUI-Florence2) |
| **WAS Node Suite** | BLIP image interrogation, wildcard/dynamic prompts | [github.com/WASasquatch/was-node-suite-comfyui](https://github.com/WASasquatch/was-node-suite-comfyui) |
| **Masquerade Nodes** | ClipSeg text-to-mask for targeted inpainting | [github.com/BadCafeCode/masquerade-nodes-comfyui](https://github.com/BadCafeCode/masquerade-nodes-comfyui) |

---

## Use Case 1: Generate Character Images to Fit a Description, Evaluate, and Fix Flaws

### Generation Phase

**Tools:** ComfyUI + any SDXL/Flux checkpoint

Core ComfyUI nodes:
- `CheckpointLoaderSimple` → load base model
- `CLIPTextEncode` (positive + negative) → text conditioning
- `KSampler` → run diffusion (typical: 20-30 steps, CFG 7-8 for SDXL)
- `VAEDecode` → decode latent to pixel image

For human characters, SDXL-based models (e.g., `juggernautXL`, `realvisxl`) or Flux produce better anatomy than SD1.5. Start at 1024×1024 for SDXL.

### Evaluation Phase

**Option A — Ollama vision model (LLaVA, llama3.2-vision, etc.)**

Ollama's `/api/chat` endpoint accepts base64-encoded images alongside vision models ([docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md)):

```json
POST http://localhost:11434/api/chat
{
  "model": "llama3.2-vision",
  "messages": [{
    "role": "user",
    "content": "Does this image match this description: [description]? List any flaws as JSON.",
    "images": ["<base64_encoded_image>"]
  }],
  "format": { "type": "object", "properties": { "matches": {"type": "boolean"}, "flaws": {"type": "array", "items": {"type": "string"}}}, "required": ["matches", "flaws"] },
  "stream": false
}
```

In ComfyUI, use an HTTP request custom node (e.g., from **rgthree Power Puter** or a Python custom node) to call Ollama, parse the JSON response, and conditionally branch the workflow.

**Option B — Florence-2 inside ComfyUI**

`Florence2Run` node (ComfyUI-Florence2) runs on-device: no external API call. Supports:
- `<CAPTION>` → describe the whole image
- `<DETAILED_CAPTION>` → detailed description
- `<OD>` → object detection with bounding boxes
- `<VQA>` → answer questions about the image (e.g., "Is the character wearing red hair?")

Pipe the caption output to a `Text Compare` node or back to Ollama text-only for scoring.

**Option C — BLIP (WAS Node Suite)**

`BLIP Analyze Image` node: generates a text caption or answers a question about the image inline, no external server needed.

### Fix Flaws Phase

**Face issues (most common)**

`FaceDetailer` node (Impact Pack):
1. Detects faces using built-in detector (UltralyticsBBoxDetector with `face_yolov8m.pt`)
2. Crops each face region
3. Runs a second KSampler pass on the crop at higher resolution with lower denoising strength (~0.4-0.5)
4. Pastes the result back

For severe face corruption: use `FaceDetailer (pipe)` for multi-pass processing. The `DetailerDebug (SEGS)` variant shows intermediate states.

**Anatomy / body issues**

`SAMDetector` + `Detailer (SEGS)` (Impact Pack): use SAM (Segment Anything Model) to isolate specific body regions (hands, arms) and run targeted inpainting passes.

**Text-described region targeting**

`Mask by Text` (Masquerade Nodes): uses ClipSeg to create a mask from a text description ("left hand", "background", "shirt"). Pipe the mask into an inpainting KSampler to fix only that region.

**Upscaling while adding detail**

`Iterative Upscale` (Impact Pack): progressive upscaling through multiple stages (e.g., 1.25× per step) with a diffusion pass at each stage. Prevents low-res artifacts from being magnified all at once.

### Iteration Loop

A full eval-and-fix loop in ComfyUI:
```
Generate → Florence2/BLIP caption → Ollama scores against description
  if score < threshold:
    → identify flaw category (face/anatomy/composition)
    → route to appropriate fixer (FaceDetailer / SAM inpaint / img2img)
    → re-evaluate
  else:
    → save output
```

ComfyUI doesn't have native conditionals, but the `Context Switch` (rgthree) and `Any Switch` nodes can branch on signal values, enabling primitive loop structures.

---

## Use Case 2: LLM-Driven Prompt Expansion for Varied Image Generation

### Goal

Take a seed character description ("a red-haired elf archer") and generate N diverse Stable Diffusion prompts for different settings, moods, lighting, and scenarios—then batch-generate all of them.

### Ollama as Prompt Engine

Send a system-prompted request to any local chat model (Llama 3, Mistral, Gemma, etc.) via `/api/generate` or `/api/chat`:

```json
POST http://localhost:11434/api/chat
{
  "model": "llama3.1",
  "messages": [
    {
      "role": "system",
      "content": "You are a Stable Diffusion prompt engineer. Given a character description, output a JSON array of 10 diverse image prompts. Each prompt should vary setting (forest, city, dungeon, beach), time of day, weather, mood, and pose. Each prompt must be a dense keyword string in SD style (comma-separated, no sentences). Include quality tags: masterpiece, highly detailed, 8k. Return ONLY valid JSON: {\"prompts\": [\"...\", \"...\"]}"
    },
    {
      "role": "user",
      "content": "red-haired elf archer, green cloak, silver bow"
    }
  ],
  "format": {"type": "object", "properties": {"prompts": {"type": "array", "items": {"type": "string"}}}, "required": ["prompts"]},
  "stream": false
}
```

Ollama's structured output (`format` field with JSON Schema) ensures parseable responses ([docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md)).

### Plush for ComfyUI (in-graph LLM)

The **Advanced Prompt Enhancer (APE)** node connects directly to a local LLM endpoint (LM Studio, Ollama via OpenAI-compatible API) or cloud APIs. From the README ([Plush README](https://github.com/glibsonoran/Plush-for-ComfyUI)):

- Takes `Prompt`, `Instruction`, optional `image`, and `Examples` as inputs
- Outputs expanded text prompt
- Configurable endpoint: point to `http://localhost:11434/v1` for Ollama's OpenAI-compatible interface

The **Style Prompt** node additionally applies an art style transformer to the prompt.

### WAS Node Suite Wildcard Syntax

For simpler randomization without an LLM, WAS Node Suite supports wildcard syntax in CLIP text encode nodes:

```
red-haired elf archer, <forest|dungeon|snowy mountain|coastal city> setting, <dawn|noon|dusk|night>, <dramatic lighting|soft lighting|foggy atmosphere>
```

Each `<option1|option2|option3>` randomly picks one per generation. Less sophisticated than LLM expansion but zero-latency.

### Batch Workflow

1. **Script or queue**: generate the prompt list externally (Python script calling Ollama API), save to a text file, then use ComfyUI's `Load Text File` node (WAS Suite) to iterate over lines.
2. **Or**: use ComfyUI's queue system — create one workflow per prompt, add all to queue.
3. **Or**: use `Text Batch` approach — some custom node packs support processing a list of prompts in a single workflow run.

Typical pipeline for each prompt:
```
Prompt string → CLIPTextEncode → KSampler (base) → VAEDecode
              → optional HiResFix (img2img at 1.5× with 0.4 denoise)
              → save to named file (include prompt hash or index)
```

### Evaluation + Filtering

After batch generation, use Ollama vision or Florence-2 to score each image against the original character description and cull low-scoring outputs before review.

---

## Use Case 3: Character Consistency for Cartoons/Comics

This is the hardest problem in local image generation. Three techniques with documented effectiveness, ordered by setup cost vs. consistency quality:

### Approach A: IP-Adapter FaceID (Zero Training)

**Best for:** quickly adapting an existing reference photo/image to new scenes without training.

**Models needed:**
- `ip-adapter-faceid-plusv2_sd15.bin` or `ip-adapter-faceid-plusv2_sdxl.bin` (HuggingFace: [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter))
- Corresponding LoRA weight (required alongside FaceID models)

**Workflow (cubiq's ComfyUI_IPAdapter_plus nodes):**

```
Reference face image
  → IPAdapterUnifiedLoader (loads FaceID model + LoRA)
  → IPAdapter (Advanced) node
      weight: ~0.8          ← lower = more prompt adherence; higher = more face fidelity
      weight_type: "linear" or "ease in-out"
  → KSampler with your scene prompt
```

Key finding from [cubiq README](https://github.com/cubiq/ComfyUI_IPAdapter_plus): "Lowering the weight to approximately 0.8, increasing generation steps, and adjusting weight type settings in the Advanced node improve prompt adherence."

The FaceID models "preserve facial identity across generations" by encoding face embeddings rather than general image style.

**Adding pose control (essential for comics):**

Combine IP-Adapter with ControlNet OpenPose:
```
Pose reference image (or drawn skeleton)
  → DWPose Estimator (comfyui_controlnet_aux) → pose keypoints
  → ControlNetApply (openpose_fullbody model)
  → merged with IP-Adapter FaceID conditioning
  → KSampler
```

This gives face consistency (IP-Adapter) + pose control (ControlNet) simultaneously.

### Approach B: Character LoRA (Training Required, Best Consistency)

**Best for:** professional cartoon/comic production where you'll generate hundreds of images of the same character.

**Training tools:**
- [Kohya_ss](https://github.com/bmaltais/kohya_ss) — most widely used LoRA trainer GUI
- AUTOMATIC1111 webui with LoRA training extension
- Dataset: 15–30 images of the character from varied angles, expressions, lighting

**Training parameters (typical):**
- Network rank (dim): 32–64
- Alpha: 16–32
- Steps: 1500–3000 (with ~20 images)
- Learning rate: 1e-4 (UNet), 5e-5 (text encoder)
- Captioning: use WD14 Tagger or BLIP to auto-caption each training image, then edit captions to consistently use a unique trigger word (e.g., `ohwx_character`)

**Inference in ComfyUI:**
```
LoRALoader (your trained .safetensors)
  weight: 0.7–1.0
  → KSampler with "ohwx_character wearing armor in a forest"
```

Stack with ControlNet OpenPose for consistent body positions across comic panels.

**Weakness:** LoRA training takes 30–90 min on a modern GPU; requires enough source images; may overfit if dataset is too small/uniform.

### Approach C: ControlNet Tile + Img2Img (Variation Without New Training)

**Best for:** generating variants of a scene where you have one good "hero" image of the character.

The ControlNet **Tile** model (listed in [ControlNet v1.1 README](https://github.com/lllyasviel/ControlNet-v1-1-nightly)) "enables detail generation and enhancement at different scales" and can preserve the overall composition/character design while allowing the diffusion model to vary details.

Workflow for comic panels:
```
Hero character image
  → ControlNet Tile preprocessor (tile_resample)
  → ControlNetApply at strength 0.6–0.8
  → img2img KSampler at denoising ~0.5–0.6
  → varied text prompt ("same character, running, rain, night")
```

Higher denoising = more variation; lower = more faithful to reference. For comics, 0.4–0.6 is the sweet spot.

### Approach D: InstantID (State-of-the-Art, Single Reference)

InstantID is a more recent approach (2024) that achieves high face consistency from a single reference image using InsightFace embeddings combined with ControlNet-like spatial conditioning. ComfyUI nodes available via [ComfyUI_InstantID](https://github.com/cubiq/ComfyUI_InstantID) (same author as IPAdapter_plus).

Key difference from IP-Adapter FaceID: InstantID uses both face ID embeddings AND a facial keypoint ControlNet simultaneously, producing stronger identity preservation across varied expressions and angles.

### Comic/Cartoon Production Workflow

A full multi-panel workflow:
```
1. CHARACTER SETUP
   └─ Reference image → IP-Adapter FaceID (or InstantID) → character embedding
   └─ Optional: trained character LoRA

2. PANEL GENERATION (per panel)
   ├─ Panel description → Ollama → expanded SD prompt
   ├─ Pose sketch / reference pose → DWPose → ControlNet OpenPose
   ├─ Apply character embedding (IP-Adapter weight ~0.8)
   ├─ Apply ControlNet OpenPose
   └─ KSampler → raw panel image

3. ENHANCEMENT
   ├─ FaceDetailer (Impact Pack) → fix any face degradation
   ├─ Iterative Upscale → 2× with detail preservation
   └─ Optional: ControlNet Tile pass for consistency across panels

4. EVALUATION
   └─ Florence-2 caption → compare against panel description
   └─ Flag panels below threshold for regeneration
```

---

## How Ollama Fits into These Pipelines

Ollama is the local inference server; the models it runs can play three distinct roles:

| Role | Model type | How |
|------|-----------|-----|
| **Prompt expansion** | Text LLM (Llama 3, Mistral, Gemma) | POST to `/api/chat`, system-prompted to output SD-style prompt variants in JSON |
| **Image evaluation** | Vision LLM (LLaVA, llama3.2-vision, moondream) | POST to `/api/chat` with base64 image attached, ask structured questions about the image |
| **Structured output** | Any model | Use `format` field with JSON Schema to get reliably parseable responses |

Ollama's OpenAI-compatible endpoint (`/v1/chat/completions`) means any tool with OpenAI API support (including Plush for ComfyUI's APE node) can talk to it by just changing the base URL to `http://localhost:11434/v1`.

---

## Summary: Tool Combinations by Goal

| Goal | Primary tools |
|------|--------------|
| Basic character generation | ComfyUI + SDXL checkpoint |
| Evaluate vs. description | Ollama vision (LLaVA) + `/api/chat` with image |
| Fix faces automatically | ComfyUI-Impact-Pack `FaceDetailer` |
| Fix specific regions | Masquerade Nodes ClipSeg → inpaint |
| LLM prompt expansion | Plush APE node → Ollama, or external Python → Ollama `/api/chat` |
| Wildcard randomization (fast) | WAS Node Suite wildcard syntax |
| Character consistency (zero training) | IP-Adapter FaceID + ControlNet OpenPose |
| Character consistency (best quality) | Trained character LoRA + ControlNet |
| Single-reference face consistency | InstantID (ComfyUI_InstantID) |
| Comic panel variation | ControlNet Tile + img2img |
| Upscale with detail | Impact Pack `Iterative Upscale` |
