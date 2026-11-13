"""Writes the ComfyUI graphs the worker needs into workflows/.

python scripts/make_graphs.py [--out workflows]

The graphs follow ComfyUI's own templates (Z-Image Turbo, Wan 2.2 14B image to video with
the lightx2v 4-step LoRAs, ACE-Step 1.5) in API format. `keyframe-edit.json` draws a frame
from a character's portrait with Qwen-Image-Edit 2511, and `keyframe-edit-place.json` from
the portrait and a picture of the place. `animate-hd.json` is the same clip
upscaled to 1080x1920 by Real-ESRGAN before the frame interpolation.

A node whose title starts with `@` is a slot the worker fills: `@prompt:text` means "put
the prompt into this node's `text`". Regenerate after changing the structure of a graph;
sizes and steps come from .env at run time.
"""

import argparse
import json
from pathlib import Path
from typing import Any

Link = tuple[str, int]

WAN_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，"
    "低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，"
    "毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}

    def add(self, kind: str, title: str | None = None, **inputs: Any) -> str:
        node_id = str(len(self.nodes) + 1)
        node: dict[str, Any] = {"class_type": kind, "inputs": inputs}
        if title:
            node["_meta"] = {"title": title}
        self.nodes[node_id] = node
        return node_id

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.nodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def out(node: str, slot: int = 0) -> Link:
    return (node, slot)


def keyframe() -> Graph:
    g = Graph()
    unet = g.add("UNETLoader", unet_name="z_image_turbo_bf16.safetensors", weight_dtype="default")
    clip = g.add("CLIPLoader", clip_name="qwen_3_4b.safetensors", type="lumina2", device="default")
    vae = g.add("VAELoader", vae_name="ae.safetensors")
    model = g.add("ModelSamplingAuraFlow", model=out(unet), shift=3)
    positive = g.add("CLIPTextEncode", "@prompt:text", clip=out(clip), text="")
    negative = g.add("ConditioningZeroOut", conditioning=out(positive))
    latent = g.add(
        "EmptySD3LatentImage", "@width:width @height:height", width=720, height=1280, batch_size=1
    )
    sampled = g.add(
        "KSampler", "@seed:seed @steps:steps",
        model=out(model), seed=0, steps=8, cfg=1, sampler_name="res_multistep",
        scheduler="simple", positive=out(positive), negative=out(negative),
        latent_image=out(latent), denoise=1,
    )  # fmt: skip
    image = g.add("VAEDecode", samples=out(sampled), vae=out(vae))
    g.add("SaveImage", images=out(image), filename_prefix="reelsmith/frame")
    return g


def animate(width: int = 480, height: int = 848, *, sharp: bool = False) -> Graph:
    g = Graph()
    loras = "wan2.2_i2v_lightx2v_4steps_lora_v1_{}_noise.safetensors"
    models = "wan2.2_i2v_{}_noise_14B_fp8_scaled.safetensors"

    def expert(noise: str) -> str:
        unet = g.add("UNETLoader", unet_name=models.format(noise), weight_dtype="default")
        lora = g.add(
            "LoraLoaderModelOnly",
            model=out(unet), lora_name=loras.format(noise), strength_model=1,
        )  # fmt: skip
        return g.add("ModelSamplingSD3", model=out(lora), shift=5)

    high, low = expert("high"), expert("low")
    clip = g.add(
        "CLIPLoader",
        clip_name="umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        type="wan",
        device="default",
    )
    vae = g.add("VAELoader", vae_name="wan_2.1_vae.safetensors")
    positive = g.add("CLIPTextEncode", "@prompt:text", clip=out(clip), text="")
    negative = g.add("CLIPTextEncode", clip=out(clip), text=WAN_NEGATIVE)
    start = g.add("LoadImage", "@image:image", image="example.png")
    video = g.add(
        "WanImageToVideo", "@length:length @width:width @height:height",
        positive=out(positive), negative=out(negative), vae=out(vae),
        width=width, height=height, length=81, batch_size=1, start_image=out(start),
    )  # fmt: skip
    shared = {
        "positive": out(video, 0), "negative": out(video, 1), "steps": 4, "cfg": 1,
        "sampler_name": "euler", "scheduler": "simple",
    }  # fmt: skip
    first = g.add(
        "KSamplerAdvanced", "@seed:noise_seed @steps:steps @split:end_at_step",
        model=out(high), add_noise="enable", noise_seed=0, latent_image=out(video, 2),
        start_at_step=0, end_at_step=2, return_with_leftover_noise="enable", **shared,
    )  # fmt: skip
    second = g.add(
        "KSamplerAdvanced", "@seed:noise_seed @steps:steps @split:start_at_step @steps:end_at_step",
        model=out(low), add_noise="disable", noise_seed=0, latent_image=out(first),
        start_at_step=2, end_at_step=4, return_with_leftover_noise="disable", **shared,
    )  # fmt: skip
    frames = g.add("VAEDecode", samples=out(second), vae=out(vae))
    if sharp:
        # Four times up, then down to the final size: crisper than stretching 480 px in ffmpeg.
        upscaler = g.add("UpscaleModelLoader", model_name="RealESRGAN_x4plus_anime_6B.pth")
        big = g.add("ImageUpscaleWithModel", upscale_model=out(upscaler), image=out(frames))
        frames = g.add(
            "ImageScale",
            image=out(big), upscale_method="lanczos", width=1080, height=1920, crop="center",
        )  # fmt: skip
    smooth = g.add(
        "RIFE VFI",
        ckpt_name="rife49.pth", frames=out(frames), clear_cache_after_n_frames=10, multiplier=2,
        fast_mode=True, ensemble=True, scale_factor=1.0, dtype="float32", torch_compile=False,
        batch_size=1,
    )  # fmt: skip
    clip_video = g.add("CreateVideo", images=out(smooth), fps=32)
    g.add(
        "SaveVideo",
        video=out(clip_video), filename_prefix="reelsmith/clip", format="auto", codec="auto",
    )  # fmt: skip
    return g


def keyframe_edit(*, place: bool = False) -> Graph:
    """Qwen-Image-Edit 2511 with the lightx2v 8-step Lightning LoRA: a new frame drawn from
    a reference of the characters' portraits, so they keep their faces and clothes, and with
    `place` from a picture of the place as well, so the room keeps its walls and furniture.
    The encoder scales the references itself and names them Picture 1 and Picture 2 to the
    model. 2511 reads its references by the index_timestep_zero method, which ComfyUI's
    template for it sets on both conditionings. Lightning runs at cfg 1, so the negative
    prompt has no effect."""
    g = Graph()
    base = g.add(
        "UNETLoader",
        unet_name="qwen_image_edit_2511_fp8_e4m3fn_scaled.safetensors",
        weight_dtype="default",
    )
    unet = g.add(
        "LoraLoaderModelOnly",
        model=out(base),
        lora_name="Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
        strength_model=1.0,
    )
    clip = g.add(
        "CLIPLoader", clip_name="qwen_2.5_vl_7b_fp8_scaled.safetensors", type="qwen_image",
        device="default",
    )  # fmt: skip
    vae = g.add("VAELoader", vae_name="qwen_image_vae.safetensors")
    model = g.add("ModelSamplingAuraFlow", model=out(unet), shift=3)
    images = {"image1": out(g.add("LoadImage", "@image:image", image="example.png"))}
    if place:
        images["image2"] = out(g.add("LoadImage", "@place:image", image="example.png"))
    conditions = []
    for title in ("@prompt:prompt", ""):
        encoded = g.add(
            "TextEncodeQwenImageEditPlus", title,
            clip=out(clip), prompt="", vae=out(vae), **images,
        )  # fmt: skip
        conditions.append(
            g.add(
                "FluxKontextMultiReferenceLatentMethod",
                conditioning=out(encoded),
                reference_latents_method="index_timestep_zero",
            )
        )
    positive, negative = conditions
    latent = g.add(
        "EmptySD3LatentImage", "@width:width @height:height", width=720, height=1280, batch_size=1
    )
    sampled = g.add(
        "KSampler", "@seed:seed @steps:steps",
        model=out(model), seed=0, steps=8, cfg=1, sampler_name="euler", scheduler="simple",
        positive=out(positive), negative=out(negative), latent_image=out(latent), denoise=1,
    )  # fmt: skip
    image = g.add("VAEDecode", samples=out(sampled), vae=out(vae))
    g.add("SaveImage", images=out(image), filename_prefix="reelsmith/frame-edit")
    return g


def score() -> Graph:
    g = Graph()
    checkpoint = g.add("CheckpointLoaderSimple", ckpt_name="ace_step_1.5_turbo_aio.safetensors")
    seconds = g.add("PrimitiveFloat", "@seconds:value", value=30.0)
    seed = g.add("PrimitiveInt", "@seed:value", value=0)
    tags = g.add(
        "TextEncodeAceStepAudio1.5", "@tags:tags",
        clip=out(checkpoint, 1), tags="", lyrics="[Instrumental]", seed=out(seed), bpm=70,
        duration=out(seconds), timesignature="4", language="en", keyscale="A minor",
        generate_audio_codes=True, cfg_scale=2, temperature=0.85, top_p=0.9, top_k=0, min_p=0,
    )  # fmt: skip
    model = g.add("ModelSamplingAuraFlow", model=out(checkpoint), shift=3)
    silence = g.add("ConditioningZeroOut", conditioning=out(tags))
    latent = g.add("EmptyAceStep1.5LatentAudio", seconds=out(seconds), batch_size=1)
    sampled = g.add(
        "KSampler", "@steps:steps",
        model=out(model), seed=out(seed), steps=8, cfg=1, sampler_name="euler",
        scheduler="simple", positive=out(tags), negative=out(silence),
        latent_image=out(latent), denoise=1,
    )  # fmt: skip
    audio = g.add("VAEDecodeAudio", samples=out(sampled), vae=out(checkpoint, 2))
    g.add("SaveAudioAdvanced", audio=out(audio), filename_prefix="reelsmith/music", format="flac")
    return g


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("workflows"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    graphs = {
        "keyframe": keyframe(),
        "keyframe-edit": keyframe_edit(),
        "keyframe-edit-place": keyframe_edit(place=True),
        "animate": animate(),
        "animate-hd": animate(sharp=True),
        "score": score(),
    }
    for name, graph in graphs.items():
        graph.save(args.out / f"{name}.json")
        print(f"wrote {args.out / name}.json ({len(graph.nodes)} nodes)")


if __name__ == "__main__":
    main()
