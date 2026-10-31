# ComfyUI workflows

The worker does not build graphs in code. Each graph is made in the ComfyUI editor,
exported, and committed here; the code only fills in a few marked inputs.

## Making one

1. `make up`, open http://127.0.0.1:8188 on the host.
2. Start from the built-in template (Workflow → Browse Templates):
   - `keyframe.json` — Z-Image Turbo text-to-image, 720×1280.
   - `animate.json` — Wan 2.2 14B image-to-video, with the two lightx2v 4-step LoRAs
     on the high- and low-noise models, then RIFE ×2 and a VideoHelperSuite
     "Video Combine" saving mp4 at 32 fps.
   - `score.json` — ACE-Step 1.5 AIO, saving flac.
   - `animate-draft.json` (optional) — Wan 2.2 TI2V 5B at 24 fps, same slots as
     `animate.json`. When it exists the worker offers it as video provider `wan-5b`,
     the cheap arm for A/B runs and drafts.
3. Get one good result by hand. Then rename the nodes the worker must fill
   (right click → Title) using `@slot:input`:

   | file | title | on which node |
   | --- | --- | --- |
   | keyframe | `@prompt:text` | positive prompt encoder |
   | keyframe | `@seed:seed` | KSampler |
   | animate | `@image:image` | Load Image |
   | animate | `@prompt:text` | positive prompt encoder |
   | animate | `@length:length` | the node with the frame count |
   | animate | `@seed:noise_seed` | **both** KSamplerAdvanced nodes |
   | score | `@tags:tags` | the ACE-Step text encoder |
   | score | `@seconds:seconds` | the empty latent audio node |
   | score | `@seed:seed` | KSampler |

4. Workflow → Export (API), save under the name above.

The worker checks the slots on start and refuses to run if a title is missing or
points at an input the node does not have, so a bad export fails at once instead of
on the fortieth job.
