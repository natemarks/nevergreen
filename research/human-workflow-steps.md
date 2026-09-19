# Human Workflow Steps: Two-Stage Image Generation (with Tool Mechanics)

What the human does, step by step — paired with what each tool does in response.
Written for a developer building a UI for this workflow.

Sources: `local-llm-image-generation.md`, `two-stage-workflow.md`

---

## Stage 1: Exploration

**Goal:** Generate 10–20 varied images from a seed idea and pick one favorite.

---

**Step 1 — Human types a seed description**

> *"red-haired elf archer, green cloak, silver bow"*

- **No tool fires yet.** This text is stored as input to the next step. No SD-style keywords needed — the LLM will expand it. The human may also set a base style (e.g. "anime cel-shaded") and a shared negative prompt ("blurry, extra limbs, watermark") that apply to all generated variants.

---

**Step 2 — Human triggers prompt expansion**

> Clicks "Expand" or equivalent button.

- **Tool:** Plush for ComfyUI — `Advanced Prompt Enhancer (APE)` node, configured to use Ollama's OpenAI-compatible endpoint (`http://localhost:11434/v1`).
- **What happens:** The APE node sends a structured chat request to Ollama:
  - **System prompt** (pre-configured): *"You are a Stable Diffusion prompt writer. Given a character description, produce a JSON array of 15 image prompts. Each prompt should vary the setting, lighting, mood, and composition while keeping the character consistent. Output only valid JSON: `{"prompts": ["...", "..."]}`.* "
  - **User message**: the seed text the human typed in Step 1.
  - **Ollama structured output** (`format` field with JSON Schema): forces the response to be a parseable `{"prompts": [...]}` object — no markdown, no preamble.
  - Ollama runs the text LLM (e.g. Llama 3, Mistral, Gemma) locally and returns the JSON array.
  - The `Extract JSON data` node (also Plush) parses the response and extracts the `prompts` array.
- **Output:** 15 SD-style keyword strings, each describing the same character in a different scenario, e.g.:
  - *"red-haired elf archer, green cloak, silver bow, ancient forest, dawn light, dew on leaves, masterpiece, 8k"*
  - *"red-haired elf archer, green cloak, silver bow, ruined dungeon, torchlight, dramatic shadows, highly detailed"*
  - ...13 more

---

**Step 3 — Human reviews expanded prompts (optional edit)**

- **Tool:** UI text list / editable fields (no inference runs).
- **What happens:** The human sees the 15 generated prompts. They can edit, delete, or add prompts before queuing. Most users skip this and accept the LLM output. Editing is useful when the LLM drifted from the character description or produced duplicates.
- **Output:** A finalized list of N prompts (typically 10–20).

---

**Step 4 — Human triggers batch generation**

> Clicks "Generate All" or queues the batch.

- **Tool:** ComfyUI + SDXL checkpoint (e.g. `juggernautXL`, `realvisxl`), executed once per prompt.
- **What happens per prompt:**
  1. `CLIPTextEncode` (positive) — encodes the expanded SD prompt into a text embedding tensor.
  2. `CLIPTextEncode` (negative) — encodes the shared negative prompt.
  3. `KSampler` — runs diffusion: typically 20–30 steps, CFG 7–8, at 1024×1024 for SDXL. Denoising starts from random noise and iteratively refines the latent toward the text conditioning.
  4. `VAEDecode` — decodes the final latent tensor to a pixel image (PNG/JPG).
  5. Image is saved with the prompt index embedded in the filename.
- **Mechanics of running N prompts:** ComfyUI queues each prompt as a separate job via its internal queue. Programmatically, each job is a POST to `http://localhost:8188/prompt` with different `CLIPTextEncode` text values. The human sees a queue counter decrement as images complete.
- **Output:** 15 images (512×512 preview thumbnails, 1024×1024 full resolution), displayed in a grid.
- **Time:** ~2–5 minutes for 15 images on a mid-range GPU (e.g. RTX 3080).

---

**Step 5 — Human picks a favorite from the grid**

> Clicks one image.

- **Tool:** UI grid view (no inference runs).
- **What happens:** The human browses the grid and clicks the image closest to their mental model. This is a subjective judgment call — typically "most aligned with the character description" rather than "technically best." The selected image is passed to Stage 2.
- **Decision point:** If nothing in the grid is close enough, the human adjusts the seed description (Step 1) or style and re-runs Stage 1. Otherwise they proceed.

---

## Stage 2: Refinement

**Goal:** Take the selected image and fix all flaws until it's publication-ready.

Assumed flaws in the selected image: bad face, wrong clothing color, distorted left hand, off-brand background.

---

**Step 6 — Human triggers upscale**

> Clicks "Upscale" (one button, no configuration).

- **Tools:** `TilePreprocessor` (comfyui_controlnet_aux) + ControlNet Tile model (`control_v11f1e_sd15_tile` or SDXL equivalent) + `KSampler`.
- **What happens:**
  1. `ImageScale` — upscales the pixel image 2× (nearest-exact or lanczos interpolation). This is a simple resize, not a diffusion step — it produces a large but blurry/pixelated image.
  2. `TilePreprocessor` (`pyrUp_iters: 3`) — preprocesses the upscaled image into tile conditioning signal that tells ControlNet to preserve the existing content structure.
  3. `ControlNetApply` (tile model, strength: 0.5–0.7) — applies the tile conditioning to the diffusion process.
  4. `VAEEncode` — re-encodes the upscaled pixel image into a latent.
  5. `KSampler` — runs diffusion at `denoise: 0.3–0.5`, 20 steps. The low denoise means the model starts close to the existing image and adds fine detail without changing composition. The tile ControlNet enforces spatial coherence.
  6. `VAEDecode` — outputs the upscaled, sharpened pixel image.
- **Output:** Same image at 2× resolution (e.g. 2048×2048), sharper with more fine detail. Face and hand flaws are now more visible at this resolution — which is intentional.
- **Note:** The denoise value (~0.4) is a pre-set default. At `>0.65` the composition starts to drift, which is why this is not user-configurable per run.

---

**Step 7 — Human triggers face fix (automated)**

> Clicks "Fix Faces" (one button, no configuration).

- **Tool:** `FaceDetailer` node (ComfyUI-Impact-Pack), backed by `UltralyticsDetectorProvider` with `face_yolov8m.pt`.
- **What happens:**
  1. `UltralyticsDetectorProvider` runs YOLO face detection on the upscaled image. It outputs bounding boxes (SEGS format) for each detected face — typically 1, sometimes 2–3 if multiple characters are present.
  2. `FaceDetailer` iterates over each bounding box:
     - Crops the face region
     - Scales it up to `guide_size` (384–512px), giving the inpainting pass more resolution to work with
     - Encodes the crop into a latent
     - Runs `KSampler` (inpainting) at `denoise: 0.4–0.6` — enough to fix artifacts while preserving identity
     - `feather: 10–20px` blends the edges of the fixed face back into the surrounding image
     - Pastes the result back at the original position
  3. If multiple faces detected, each is processed in sequence.
- **Output:** Same image with all faces replaced by sharper, more anatomically correct versions. The rest of the image is pixel-identical to the input.
- **Typical outcome:** Resolves ~80% of face issues in one pass. A second FaceDetailer pass can help marginal cases.

---

**Step 8 — Human fixes wrong clothing color**

> Types region: *"cloak"* — Types fix prompt: *"green cloak, smooth fabric"* — Clicks "Fix Region."

- **Tools:** `Mask by Text` (Masquerade Nodes / ClipSeg) + `VAEEncodeForInpaint` + `KSampler` (inpainting).
- **What happens:**
  1. `Mask by Text` — runs ClipSeg on the image with the human's region text (*"cloak"*). ClipSeg is a zero-shot segmentation model that outputs a float mask tensor: high values where the model thinks "cloak" is, low values elsewhere.
  2. `Mask Morphology` (dilate, ~5–10px) — expands the mask slightly to ensure edge pixels are included in the fix region.
  3. `VAEEncodeForInpaint` — encodes the image into a latent, applying the mask so only the masked region is treated as "to be regenerated."
  4. `CLIPTextEncode` — encodes the human's fix prompt (*"green cloak, smooth fabric"*) as the inpainting conditioning.
  5. `KSampler` (inpainting mode, `denoise: 0.5–0.65`) — regenerates only the masked latent region guided by the fix prompt. Unmasked pixels are preserved exactly.
  6. `VAEDecode` — outputs the image with the cloak region replaced.
- **Output:** Same image with only the cloak region changed. All other pixels untouched.
- **If ClipSeg fails:** The human makes the description more specific (*"upper body cloak"*, *"dark green fabric over shoulders"*) and re-runs. One retry usually resolves it. If ClipSeg still fails, fall back to Step 10 (manual painting).

---

**Step 9 — Human fixes distorted hand**

> Types region: *"left hand"* — Types fix prompt: *"normal human left hand, 5 fingers, female, relaxed grip"* — Clicks "Fix Region."

- **Tools:** Same pipeline as Step 8: `Mask by Text` (ClipSeg) + `VAEEncodeForInpaint` + `KSampler`.
- **What happens:** Identical mechanics to Step 8. ClipSeg generates a mask over the left hand region; inpainting regenerates it guided by the fix prompt.
- **Key difference:** Hands are harder than clothing — ClipSeg has more difficulty reliably isolating a single hand vs. a large garment. The inpainting model also struggles more with hand anatomy.
- **Typical iteration count:** 2–3 runs. After each run the human inspects the hand: if still distorted, they re-run (sometimes with a slightly varied fix prompt, e.g. adding *"anatomically correct"* or *"4k detail"*). If the LLM-written fix prompt isn't helping, the human can ask the LLM to rewrite it (Plush APE Stage 2 mode — see below).
- **LLM assistance for the fix prompt (optional):** The human can invoke a Stage 2 APE node with this system prompt: *"You are a Stable Diffusion inpainting prompt specialist. Write a precise prompt to fix a distorted hand while matching the overall image style."* The LLM outputs a more precise inpainting prompt than the human wrote. The `Context Output` chaining feature in Plush passes the original Stage 1 style context so the fix stays consistent.
- **Fallback to manual painting:** If ClipSeg can't isolate the hand, the human opens MaskEditor (right-click the image in ComfyUI), brushes over the hand, and runs the inpaint pass with the manual mask instead.

---

**Step 10 — Human fixes the background**

Two paths depending on whether the background is simple or irregular.

**Path A — Simple, describable background:**

> Types region: *"background"* — Types fix prompt: *"misty forest, green trees, soft light"* — Clicks "Fix Region."

- **Tools:** `Mask by Text` (ClipSeg) + `VAEEncodeForInpaint` + `KSampler` — same pipeline as Steps 8–9.
- **What happens:** ClipSeg generates a mask for everything it recognizes as background. This works well when the background is visually distinct from the character (different textures, colors). The inpaint pass replaces it with the described scene.

**Path B — Irregular background (partially behind character):**

> Opens mask painter — Brushes over background areas — Types fix prompt — Clicks "Fix Region."

- **Tools:** ComfyUI MaskEditor (built-in, right-click → "Open in MaskEditor") or `MaskPainter` node (Impact Pack, inline brush interface). Then `VAEEncodeForInpaint` + `KSampler`.
- **What happens:**
  1. Human opens MaskEditor and sees the image with a brush. They paint white over the background regions they want replaced, carefully avoiding the character edges.
  2. The mask is exported as a tensor and fed into `VAEEncodeForInpaint`.
  3. `KSampler` runs inpainting with the manual mask — only the painted region regenerates.
  4. `Mask blur` (4–8px) feathers the edges for seamless blending.
- **Typical issues:** Seam visible at the character/background boundary if mask edges were too hard or the replacement scene's lighting doesn't match the character. Fix: increase mask blur, or run a second very-low-denoise (0.2) pass over the seam area with no prompt change.

---

**Step 11 — Human reviews final image**

> Inspects the full image at full resolution.

- **No tool fires yet.** This is a visual judgment pass.
- Three outcomes:
  1. **Done:** all flaws are fixed, image is publication-ready.
  2. **Minor remaining issues** (e.g. one ear slightly off): repeat the relevant step (text-directed or manual inpainting for that specific region).
  3. **Fix introduced a new problem** (e.g. fixing the hand changed the sleeve color): mask and fix the newly broken region using the same pipeline.

- **Typical total Stage 2 iterations:** 3–6 passes across all flaw types. Each pass takes 10–60 seconds depending on resolution and hardware.

---

## Summary: What Needs to Be UI-Supported

| Step | User input required | Tool(s) invoked | Automation level |
|------|---------------------|-----------------|-----------------|
| Seed description | Free text | (none yet) | Human |
| Set batch size / style | Simple form fields | (none yet) | Human |
| Prompt expansion | One button | Ollama LLM → Plush APE | Fully automated |
| Review/edit prompts | Optional edits | (none) | Human |
| Batch generation | One button | ComfyUI KSampler × N | Fully automated |
| Select favorite | Click one image | (none) | Human |
| Upscale | One button | ControlNet Tile + KSampler | Fully automated |
| Fix faces | One button | FaceDetailer (YOLO + inpaint) | Fully automated |
| Fix region by name | Region text + fix prompt | ClipSeg mask + inpaint KSampler | Semi-automated |
| Fix region by painting | Brush + fix prompt | MaskEditor + inpaint KSampler | Manual mask |
| Iterate on a fix | Re-run same step | Same as above | One button |
| LLM-assisted fix prompt | Flaw description | Ollama LLM → Plush APE | Semi-automated |
