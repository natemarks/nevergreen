# Image Metadata in AI Image Generation Workflows

Research compiled from primary sources. All claims cite their source.

---

## How Tools Embed Metadata in Saved Images

### ComfyUI — Two PNG tEXt Chunks

`SaveImage` (defined in [`nodes.py`](https://github.com/comfyanonymous/ComfyUI/blob/master/nodes.py)) writes metadata using PIL's `PngInfo`, which stores data as standard PNG tEXt chunks:

```python
metadata = PngInfo()
if prompt is not None:
    metadata.add_text("prompt", json.dumps(prompt))
if extra_pnginfo is not None:
    for x in extra_pnginfo:
        metadata.add_text(x, json.dumps(extra_pnginfo[x]))
img.save(file, pnginfo=metadata, compress_level=self.compress_level)
```

This produces **two tEXt chunks**:

| PNG tEXt key | Contents | What it contains |
|---|---|---|
| `"prompt"` | JSON string | The API execution graph — every node's class_type, inputs, and connections |
| `"workflow"` | JSON string | The full visual workflow — node positions, UI state, comments (sent by the frontend via `extra_pnginfo`) |

The `"workflow"` key name comes from the frontend: the browser sends `extra_data: { extra_pnginfo: { workflow: {...} } }` when queuing a prompt via the `/prompt` API endpoint. `execution.py` passes `extra_data["extra_pnginfo"]` through to each node's hidden inputs. ([`execution.py` source](https://github.com/comfyanonymous/ComfyUI/blob/master/execution.py))

**Disabling metadata:** Running ComfyUI with `--disable-metadata` skips writing both chunks.

**Reading back:** In the ComfyUI UI, drag-and-drop any generated PNG onto the canvas to restore its full workflow. The frontend reads the `"workflow"` tEXt chunk and rehydrates the graph. This is the primary recovery mechanism — no extra node is needed.

**Programmatic reading (Python):**
```python
from PIL import Image
img = Image.open("ComfyUI_00001_.png")
import json
prompt_graph = json.loads(img.info["prompt"])    # node execution graph
workflow_json = json.loads(img.info["workflow"]) # visual workflow
```

### A1111 — Single PNG tEXt Chunk

A1111 writes a single tEXt chunk with key `"parameters"` ([`modules/images.py`](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/images.py)):

```python
pnginfo_data = PngImagePlugin.PngInfo()
pnginfo_data.add_text("parameters", geninfo)
```

The value is a human-readable multi-line string:

```
a weathered sailor with a red coat, detailed face, dramatic lighting

Negative prompt: ugly, blurry, deformed

Steps: 25, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 3482912847,
Size: 1024x1024, Model hash: 4199bcdd14, Model: juggernautXL_v9,
Clip skip: 2
```

Fields included: Steps, Sampler, CFG scale, Seed, Size, Model hash, Model name, Clip skip, Hires settings, LoRA names and weights, ControlNet settings. Parsed by `parse_generation_parameters()` in [`modules/infotext_utils.py`](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/infotext_utils.py).

**Reading back:** A1111's PNG Info tab reads this directly. The "Send to img2img" / "Send to inpainting" buttons pre-fill the generation form with all extracted parameters — this is the native Stage 2 on-ramp.

### WAS Node Suite — Same as ComfyUI + WebP EXIF

WAS Suite's `Image Save` node mirrors ComfyUI's PNG format and adds WebP EXIF support ([`WAS_Node_Suite.py`](https://github.com/WASasquatch/was-node-suite-comfyui/blob/master/WAS_Node_Suite.py)):

- **PNG:** `"prompt"` and `"workflow"` tEXt chunks (identical to ComfyUI)
- **WebP:** EXIF tag `0x010f` (ImageMake) stores `"Prompt:" + json`, tag `0x010e` (ImageDescription) stores `"Workflow:" + json`
- Has an `embed_workflow` toggle ("true"/"false") to control whether metadata is written

---

## What Fields Are Critical for Stage 2 Refinement

| Field | Where it lives | Why it matters in Stage 2 |
|---|---|---|
| Positive prompt | `prompt` chunk → `CLIPTextEncode` node inputs | Must be passed to inpainting KSampler as base context to prevent style drift |
| Negative prompt | `prompt` chunk → second `CLIPTextEncode` | Same reason — omitting it weakens the style guard |
| Model (checkpoint) | `prompt` chunk → `CheckpointLoaderSimple` | Must reload the same model; different model = radically different style |
| Sampler + steps | `prompt` chunk → `KSampler` | Minor — but matching sampler avoids subtle texture differences |
| CFG scale | `prompt` chunk → `KSampler` | Match it; higher CFG during inpaint causes harsh seams at mask edges |
| Seed | `prompt` chunk → `KSampler` | Optional: reusing seed for inpaint produces more coherent results; changing it is valid |
| LoRA names + weights | `prompt` chunk → `LoraLoader` nodes | Required if a character LoRA was active — forgetting it causes the face/style to change |

---

## Why Inpainting Needs the Original Prompt

The inpainting KSampler runs diffusion *inside* the mask but is conditioned on the full image context *outside* it. If you pass a fix-only prompt (`"detailed fingers, correct anatomy"`) without the original positive conditioning, the diffusion model loses the style anchor. Symptoms:
- Color palette shift at mask boundaries
- Texture mismatch (e.g., painted brush strokes replaced by photorealistic skin inside the mask)
- Art style inconsistency ("anime" → "realistic" leak)

**Best practice:** concatenate original prompt + fix suffix:
```
original: "anime warrior woman, dramatic lighting, blue armor, detailed face"
fix prompt: "anime warrior woman, dramatic lighting, blue armor, detailed face, perfect hands, correct anatomy, detailed fingers"
```

The negative prompt should also match the original. Pass both to the inpainting KSampler's conditioning inputs.

---

## Stage 1 Changes: Ensuring Metadata is Saved

**No changes required** if using ComfyUI's `SaveImage` node and not running with `--disable-metadata`. The workflow JSON is automatically embedded in every PNG by default.

Checklist:
- Use `SaveImage` (not `PreviewImage` — that node does not embed metadata)
- Do NOT pass `--disable-metadata` on startup
- Include a meaningful `filename_prefix` to make Stage 1 images identifiable

Optional: Use WAS Suite's `Image Save` if you want WebP output or a custom output path, and leave `embed_workflow = true`.

---

## Stage 2 Changes: Loading and Using Metadata

### Option A — ComfyUI UI drag-and-drop (zero-code)

1. Drag the selected Stage 1 PNG onto the ComfyUI canvas
2. The full Stage 1 workflow loads automatically from the `"workflow"` tEXt chunk
3. Extend this graph: add `VAEEncodeForInpaint`, `Mask by Text`, inpainting `KSampler` nodes
4. Modify the positive `CLIPTextEncode` to append the fix suffix
5. Run — the original model, LoRAs, sampler, and CFG are all already wired in from the restored workflow

This is the standard community approach: restore the full generation context, then extend it for inpainting.

### Option B — A1111 PNG Info tab

1. Upload Stage 1 image to **PNG Info** tab
2. Click "Send to inpainting"
3. A1111 pre-fills: model, prompt, negative prompt, seed, sampler, CFG, steps
4. Draw mask manually or use the inpainting tab's brush
5. Write fix suffix in the prompt field (or append to existing prompt)
6. Generate

### Option C — Programmatic (custom Python node / script)

For automated pipelines (e.g., batch refinement), read metadata from Python:

```python
from PIL import Image
import json

img = Image.open("output/ComfyUI_00042_.png")
prompt_graph = json.loads(img.info["prompt"])

# Extract positive prompt text from the node graph
# CLIPTextEncode nodes have a "text" input
clip_nodes = {
    k: v for k, v in prompt_graph.items()
    if v.get("class_type") == "CLIPTextEncode"
}
# First CLIPTextEncode connected to KSampler's "positive" port is the positive prompt
```

There is no widely-adopted dedicated ComfyUI "Read PNG Metadata" node in the main ecosystem (as of research date). The standard approach is Option A (drag-and-drop) or a custom Python script node using PIL.

---

## Summary: Workflow Changes per Stage

| | Stage 1 | Stage 2 |
|---|---|---|
| **Required change** | None — `SaveImage` handles it | Load PNG into ComfyUI via drag-and-drop to restore original graph |
| **What you gain** | Every output PNG is self-describing | Original model, LoRAs, prompt, sampler all pre-wired |
| **Risk if skipped** | Metadata not written, Stage 2 requires manual reconstruction | Style drift, wrong model, missing LoRA = incoherent fix |
| **Gotcha** | `PreviewImage` nodes do NOT write metadata | `--disable-metadata` flag silently breaks this whole workflow |

Sources:
- [ComfyUI `nodes.py` — SaveImage](https://github.com/comfyanonymous/ComfyUI/blob/master/nodes.py)
- [ComfyUI `execution.py` — extra_pnginfo propagation](https://github.com/comfyanonymous/ComfyUI/blob/master/execution.py)
- [A1111 `modules/images.py`](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/images.py)
- [A1111 `modules/infotext_utils.py`](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/infotext_utils.py)
- [WAS Node Suite `WAS_Node_Suite.py`](https://github.com/WASasquatch/was-node-suite-comfyui/blob/master/WAS_Node_Suite.py)
