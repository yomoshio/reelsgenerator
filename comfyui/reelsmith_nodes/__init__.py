"""Reelsmith as ComfyUI nodes: an idea becomes a job, and each stage of the pipeline is a
node that moves the job on. Link this folder into ComfyUI/custom_nodes and install the
reelsmith package into ComfyUI's Python; docs/comfyui.md has the two commands.

The nodes only pass a job's id along the wire. The work is reelsmith.graph, which skips a
stage already done with the same settings and redoes one whose settings changed."""

import os
import shutil
from pathlib import Path
from typing import Any

import folder_paths  # ComfyUI's own module

from reelsmith import graph

ROOT = os.environ.get("REELSMITH_ROOT", str(Path(__file__).resolve().parents[2]))
CATEGORY = "reelsmith"
JOB = "RS_JOB"
SETTINGS = "RS_SETTINGS"


def _settings(options: dict[str, Any] | None) -> Any:
    options = dict(options or {})
    return graph.settings(options.pop("root", ROOT), **options)


def _styles() -> list[str]:
    found = sorted(p.name for p in (Path(ROOT) / "styles").iterdir() if p.is_dir())
    return found or ["blackout"]


class Settings:
    """Where the models are and which of them do what. Left empty, a field keeps the value
    of the reelsmith folder's .env."""

    CATEGORY, FUNCTION = CATEGORY, "run"
    RETURN_TYPES, RETURN_NAMES = (SETTINGS,), ("settings",)

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        text = ("STRING", {"default": ""})
        return {
            "required": {
                "tts": (["chatterbox", "qwen"],),
                "staging": (["sheet", "coder"],),
            },
            "optional": {
                "root": ("STRING", {"default": ROOT}),
                "llm_url": text, "speech_url": text, "voice_url": text,
                "planner": text, "coder": text, "vision": text,
            },
        }  # fmt: skip

    def run(self, **options: Any) -> tuple[dict[str, Any]]:
        return ({k: v for k, v in options.items() if v != ""},)


class Idea:
    """An idea or a short synopsis in a style: the job the rest of the graph works on."""

    CATEGORY, FUNCTION = CATEGORY, "run"
    RETURN_TYPES, RETURN_NAMES = (JOB,), ("job",)

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "style": (_styles(),),
            },
            "optional": {"settings": (SETTINGS,)},
        }

    def run(self, text: str, style: str, settings: dict[str, Any] | None = None) -> tuple[str]:
        return (graph.job_for(_settings(settings), text, style).id,)


class _Stage:
    CATEGORY, FUNCTION = CATEGORY, "run"
    RETURN_TYPES, RETURN_NAMES = (JOB,), ("job",)
    STEPS: tuple[str, ...] = ()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"job": (JOB,)}, "optional": {"settings": (SETTINGS,)}}

    async def run(self, job: str, settings: dict[str, Any] | None = None) -> tuple[str]:
        """Async, so ComfyUI's own loop keeps serving its page while the models work."""
        made = _settings(settings)
        for step in self.STEPS:
            await graph.advance(made, job, step)
        return (job,)


class Write(_Stage):
    """The story: plan, beats, cast cards and staging."""

    STEPS = ("write",)


class Voice(_Stage):
    """The narrator reads every beat, and each word gets the moment it is heard."""

    STEPS = ("voice",)


class Stage(_Stage):
    """Every beat staged: a sheet filled by the planner, or code written by the coder."""

    STEPS = ("stage",)


class Render(_Stage):
    """Every beat drawn frame by frame and joined with music into final.mp4."""

    STEPS = ("render", "assemble")


class Film(_Stage):
    """The whole pipeline in one node, for a graph of three nodes."""

    STEPS = tuple(graph.ORDER)


class Preview:
    """Shows a job: the film when there is one, else the middle keyframe of every beat."""

    CATEGORY, FUNCTION = CATEGORY, "run"
    RETURN_TYPES, RETURN_NAMES = ("STRING", "STRING"), ("film_path", "lines")
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"job": (JOB,)}, "optional": {"settings": (SETTINGS,)}}

    def run(self, job: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        seen = graph.seen(_settings(settings), job)
        out = Path(folder_paths.get_output_directory()) / "reelsmith"
        out.mkdir(parents=True, exist_ok=True)
        shown = []
        for path in [seen["film"]] if seen["film"] else seen["keys"]:
            name = f"{seen['job']}-{path.name}"
            shutil.copyfile(path, out / name)
            shown.append({"filename": name, "subfolder": "reelsmith", "type": "output"})
        lines = "\n".join(f"{n}. {line}" for n, line in enumerate(seen["lines"], 1))
        ui: dict[str, Any] = {"images": shown, "text": [f"{seen['job']}: {seen['status']}"]}
        if seen["film"]:
            ui["animated"] = (True,)
        return {"ui": ui, "result": (str(seen["film"] or ""), lines)}


NODE_CLASS_MAPPINGS = {
    "ReelsmithSettings": Settings, "ReelsmithIdea": Idea, "ReelsmithWrite": Write,
    "ReelsmithVoice": Voice, "ReelsmithStage": Stage, "ReelsmithRender": Render,
    "ReelsmithFilm": Film, "ReelsmithPreview": Preview,
}  # fmt: skip
NODE_DISPLAY_NAME_MAPPINGS = {
    "ReelsmithSettings": "Reelsmith · настройки", "ReelsmithIdea": "Reelsmith · идея",
    "ReelsmithWrite": "Reelsmith · сценарий", "ReelsmithVoice": "Reelsmith · голос",
    "ReelsmithStage": "Reelsmith · постановка", "ReelsmithRender": "Reelsmith · рендер",
    "ReelsmithFilm": "Reelsmith · ролик целиком", "ReelsmithPreview": "Reelsmith · просмотр",
}  # fmt: skip
