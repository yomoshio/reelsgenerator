"""The graphs in workflows/ are what the worker sends to ComfyUI; these checks catch a
regenerated graph that lost a slot before a real run does."""

import json
from pathlib import Path

import pytest

from reelsmith.services.comfy import Workflow

GRAPHS = Path(__file__).parent.parent / "workflows"
NEEDS = {
    "keyframe": ("prompt", "seed", "width", "height", "steps"),
    "animate": ("image", "prompt", "length", "seed", "width", "height", "steps", "split"),
    "animate-hd": ("image", "prompt", "length", "seed", "width", "height", "steps", "split"),
    "score": ("tags", "seconds", "seed", "steps"),
}


@pytest.mark.parametrize("name", sorted(NEEDS))
def test_every_graph_has_the_slots_the_worker_fills(name: str) -> None:
    Workflow.load(GRAPHS / f"{name}.json").require(*NEEDS[name])


def test_the_hd_graph_upscales_before_interpolating() -> None:
    graph = json.loads((GRAPHS / "animate-hd.json").read_text(encoding="utf-8"))
    kinds = {node_id: node["class_type"] for node_id, node in graph.items()}
    rife = next(node for node in graph.values() if node["class_type"] == "RIFE VFI")

    assert "ImageUpscaleWithModel" in kinds.values()
    assert kinds[rife["inputs"]["frames"][0]] == "ImageScale"


def test_the_plain_graph_has_no_upscaler() -> None:
    graph = json.loads((GRAPHS / "animate.json").read_text(encoding="utf-8"))

    assert "ImageUpscaleWithModel" not in {node["class_type"] for node in graph.values()}
