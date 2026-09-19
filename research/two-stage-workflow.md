# Two-Stage Image Generation Workflow: Infrastructure Details

Research compiled from primary sources. Picks up where `local-llm-image-generation.md` leaves off.

---

## Overview

The two stages have different goals and therefore different infrastructure:

| | Stage 1 — Exploration | Stage 2 — Refinement |
|---|---|---|
| **Goal** | Generate many varied candidates | Fix a specific chosen image |
| **LLM role** | Creative expander (many prompts) | Targeted fixer (one inpainting prompt) |
| **Output** | 10–20 images to pick from | One polished final image |
| **Masking** | None | Automated, text-directed, or manual |

---

## Stage 1: Exploration / Batch Generation

### LLM Prompt Expansion via Plush for ComfyUI

**Tool:** [Plush for ComfyUI](https://github.com/glibsonoran/Plush-for-ComfyUI) — `Advanced Prompt Enhancer (APE)` node

**How it works:**
1. Set `AI_Service` to `Ollama (URL)` in the APE node
2. APE shows an `Ollama_model` dropdown that lists models already loaded in Ollama (models must be loaded before starting ComfyUI)
3. Write a system prompt instructing the LLM to generate N varied SD prompts as a JSON array, e.g.:
   ```
   You are a Stable Diffusion prompt writer. Given a character description, 
   produce a JSON array of 15 image prompts. Each prompt should vary the 
   setting, lighting, mood, and composition while keeping the character consistent.
   Output only valid JSON: {"prompts": ["...", "...", ...]}.
   ```
4. Connect the APE `text` output → `Extract JSON data` node (also Plush) to parse the array
5. Route each prompt string to separate `CLIPTextEncode` nodes feeding separate `KSampler` runs

**Key APE features for Stage 1:**
- `Additional Parameter` node can force JSON output (`response_format: {"type": "json_object"}`)
- `Extract JSON data` node queries by key name to pull the prompts array out of the response
- `Random Output` and `Random Mixer` nodes (Plush) can randomly shuffle prompt order

### Batch Generation Mechanics in ComfyUI

ComfyUI has three ways to generate multiple images from varied prompts:

**Option A — Built-in wildcards** (no extra nodes needed)  
ComfyUI natively supports `{option1|option2|option3}` syntax in `CLIPTextEncode`:
> "You can use {day|night}, for wildcard/dynamic prompts. With this syntax '{wild|card|test}' will be randomly replaced by either 'wild', 'card' or 'test' by the frontend every time you queue the prompt."  
> Source: [ComfyUI README](https://github.com/comfyanonymous/ComfyUI)

Each press of the Queue button picks one random option. To generate 20 images, queue 20 times (use the batch count field above the Queue button).

**Option B — `batch_size` in KSampler**  
Set `batch_size` > 1 on the `KSampler` node to generate N images from the *same* prompt simultaneously. Useful for seed variation, not prompt variation.

**Option C — ComfyUI Queue API (programmatic)**  
POST to `http://localhost:8188/prompt` with different `CLIPTextEncode` text values for each job. Enables fully automated batch generation from a list of LLM-generated prompts.

---

## Stage 2: Refinement

### Text-Only vs. Masking — When to Use Each

**Text-only (img2img at low denoise):**
- Set `denoise` to 0.3–0.5 on the `KSampler`
- Works for: overall stylistic tweaks, color corrections across the whole image, slight pose adjustments
- Fails for: fixing one specific region (the whole image drifts slightly, often breaking what was working)
- Verdict: use only for global changes. For any localized flaw, masking is almost always better.

**Masking (inpainting):**
- Regenerates only the masked region; everything outside stays identical
- Much more precise; lets you fix "the face looks melted" without disturbing the rest of the image
- All serious workflows use masking for targeted fixes
- Three sub-approaches below, used in combination

### Approach A: Automated Masking — FaceDetailer (Impact Pack)

**Tool:** [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) — `FaceDetailer` node

This is fully automated: no user input per image.

**How it works:**
1. `UltralyticsDetectorProvider` (from Impact Subpack) or `ONNXDetectorProvider` detects face bounding boxes in the image automatically
2. `FaceDetailer` crops each detected face, scales it up, runs KSampler (inpainting) at that higher resolution, then pastes the improved face back seamlessly
3. Typical settings: `guide_size` 384–512px, `denoise` 0.4–0.6, `feather` 10–20px for smooth blending

**Node chain:**
```
image → FaceDetailer (with BBOX_DETECTOR from UltralyticsDetectorProvider + KSampler settings) → enhanced image
```

**Also available:** `MaskDetailer (pipe)` for arbitrary pre-computed masks, `Detailer (SEGS)` for any detected region.

### Approach B: Text-Directed Masking — Mask by Text (Masquerade Nodes)

**Tool:** [masquerade-nodes-comfyui](https://github.com/BadCafeCode/masquerade-nodes-comfyui) — `Mask by Text` node

Uses ClipSeg to generate a mask from a text description of the region to fix.

**How it works:**
1. `Mask by Text` takes the image + a text `prompt` (e.g. `"left hand"`, `"hair"`, `"jacket collar"`) and returns a mask of that region
2. Chain: `Mask by Text` → `Mask Morphology` (dilate to expand mask slightly) → `VAEEncodeForInpaint` → `KSampler` (inpainting model)
3. For multiple problem regions: chain multiple `Mask by Text` nodes with `Combine Masks (Union)` to merge them

**Key parameters:**
- `precision`: threshold for ClipSeg confidence — higher = tighter mask
- `normalize`: helps when ClipSeg inconsistently recognizes the region

**When to use vs. FaceDetailer:** FaceDetailer is better for faces (more reliable detector). `Mask by Text` handles anything else — hands, clothing items, backgrounds, specific body parts.

### Approach C: Manual Mask Painting

**ComfyUI:** Right-click any image node → "Open in MaskEditor" (built-in). Also `MaskPainter` node from Impact Pack which embeds a paint interface inline.

**Automatic1111:** Dedicated `img2img → Inpainting` tab with brush tool, hardness controls, and mask blur settings.

**When to use:** When the problem region is irregular, hard to describe in text, or ClipSeg fails to isolate it. Also useful when you want precise control over exactly what gets regenerated (e.g., fix only the right eye, not both).

**Typical A1111 inpainting settings:**
- `Inpaint area: Only masked` — crops and upscales just the masked region for better detail
- `Mask blur`: 4–8px for seamless blending
- `Denoising strength`: 0.5–0.75 (higher = more creative license in the masked region)

### LLM Role in Stage 2 Refinement Prompts

Stage 2 uses the LLM differently from Stage 1. Instead of "generate many ideas," the prompt is "generate one targeted fix."

**System prompt template for Stage 2 (Plush APE):**
```
You are a Stable Diffusion inpainting prompt specialist. 
The user will describe a specific flaw in an image and the region being inpainted.
Write a precise inpainting prompt that corrects the flaw while matching the overall 
image style. Include the original character description for consistency.
Output only the prompt text, no explanation.
```

**User message example:**
```
The character's left hand looks distorted and has 6 fingers. 
Inpainting region: left hand. 
Character style: anime, cel-shaded, female warrior in red armor.
```

**Plush feature — chained context:** The APE node's `Context Output` lets you chain multiple APE nodes so each shares conversation history. This means the Stage 2 refinement node can receive the original Stage 1 prompt as context, ensuring stylistic consistency.

**Plush example workflow:** The `Agent-ImageEvaluator.png` example workflow shipped with Plush demonstrates image evaluation + prompt improvement: it evaluates the generated image against the original prompt, then produces a list of specific improvements — this output can feed directly into a refinement pass.

### ControlNet Tile Upscale Workflow

**Tool:** `TilePreprocessor` node from [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux)  
**ControlNet model needed:** `control_v11f1e_sd15_tile` (SD1.5) or `controlnet-tile-sdxl` (SDXL)

**Purpose:** Upscale while sharpening fine detail, without changing composition. The tile ControlNet forces the model to stay coherent with the existing image content.

**Node chain:**
```
image
  → ImageScale (2–4x, method: nearest-exact or lanczos)
  → TilePreprocessor (pyrUp_iters: 3)
  → ControlNetApply (tile model, strength: 0.5–0.7)
  → VAEEncode
  → KSampler (denoise: 0.3–0.5, steps: 20)
  → VAEDecode
  → output upscaled image
```

**Critical parameter — denoise:**
- `0.3–0.4`: preserves original content closely, just sharpens
- `0.5–0.6`: allows moderate changes, good balance point
- `>0.65`: risks drifting away from the original composition

**Combining upscale + face fix:** Run ControlNet Tile upscale first, then pipe the upscaled image through FaceDetailer. Working at higher resolution gives FaceDetailer more pixels to improve, and the tile pass often reveals face flaws (like softness at 512px) that warrant fixing.

**Alternative upscale tools in Impact Pack:**
- `PixelKSampleUpscalerProvider`: upscale model (e.g., `4x-UltraSharp.pth`) → pixel upscale → re-encode → KSampler
- `PixelTiledKSampleUpscalerProvider`: same but uses tiled VAE to avoid VRAM OOM at 4K+

---

## Putting It Together: Full Two-Stage Pipeline

```
STAGE 1 (Exploration)
─────────────────────
seed_description
  → APE node (Ollama, "generate 15 varied SD prompts as JSON")
  → Extract JSON data
  → [15 prompt strings]
  → [15 × KSampler runs] (batch via queue or API)
  → [15 images]
  → [human selects best]

STAGE 2 (Refinement)  
─────────────────────
selected_image
  → ControlNet Tile upscale (2x, denoise 0.4)
  → FaceDetailer (auto-fix all faces)
  → [identify remaining flaws by eye]
  → APE node (Ollama, "write inpainting prompt for this specific flaw")
  → Mask by Text (ClipSeg masks the problem region) OR manual MaskPainter
  → VAEEncodeForInpaint → KSampler (inpaint, denoise 0.5–0.65)
  → paste back → final image
```

The LLM touches Stage 2 in two places: generating the targeted inpaint prompt, and (optionally) evaluating the image to identify what flaws remain after each pass.
