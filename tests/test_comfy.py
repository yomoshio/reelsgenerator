from pathlib import Path
from typing import Any

import httpx
import pytest

from reelsmith.models import StageError
from reelsmith.services.comfy import (
    ComfyAnimator,
    ComfyClient,
    ComfyPainter,
    Graph,
    Output,
    Workflow,
    WorkflowMismatch,
    wan_length,
)


def _wan_graph() -> Graph:
    return {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "@prompt:text"}},
        "52": {"class_type": "LoadImage", "inputs": {"image": "x.png"}, "_meta": {"title": "@image:image"}},
        "57": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 0}, "_meta": {"title": "@seed:noise_seed"}},
        "58": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 0}, "_meta": {"title": "@seed:noise_seed"}},
        "63": {"class_type": "WanImageToVideo", "inputs": {"length": 81}, "_meta": {"title": "@length:length"}},
        "8": {"class_type": "VAEDecode", "inputs": {}, "_meta": {"title": "VAE Decode"}},
    }  # fmt: skip


def test_bind_fills_every_node_that_shares_a_slot() -> None:
    graph = Workflow("animate", _wan_graph()).bind(seed=7, prompt="fog rolls in")

    assert graph["57"]["inputs"]["noise_seed"] == 7
    assert graph["58"]["inputs"]["noise_seed"] == 7
    assert graph["6"]["inputs"]["text"] == "fog rolls in"


def test_bind_leaves_the_template_untouched() -> None:
    flow = Workflow("animate", _wan_graph())
    flow.bind(seed=1)

    assert flow.bind(seed=2)["57"]["inputs"]["noise_seed"] == 2
    assert _wan_graph()["57"]["inputs"]["noise_seed"] == 0


def test_bind_rejects_a_slot_the_graph_does_not_have() -> None:
    with pytest.raises(WorkflowMismatch, match="cfg"):
        Workflow("animate", _wan_graph()).bind(cfg=5)


def test_require_fails_fast_on_missing_slot() -> None:
    with pytest.raises(WorkflowMismatch, match="tags"):
        Workflow("score", _wan_graph()).require("seed", "tags")


def test_title_must_point_at_a_real_input() -> None:
    graph: Graph = {"1": {"inputs": {"text": ""}, "_meta": {"title": "@prompt:txt"}}}
    with pytest.raises(WorkflowMismatch, match="@slot"):
        Workflow("broken", graph)


@pytest.mark.parametrize(
    ("seconds", "frames"),
    [(5.0, 81), (2.0, 33), (4.1, 69), (8.0, 129)],
)
def test_wan_length_is_4k_plus_1_and_never_shorter(seconds: float, frames: int) -> None:
    length = wan_length(seconds)

    assert length == frames
    assert (length - 1) % 4 == 0
    assert length >= seconds * 16


def _knob_graph() -> Graph:
    return {
        "1": {"inputs": {"text": ""}, "_meta": {"title": "@prompt:text"}},
        "2": {"inputs": {"width": 1, "height": 1}, "_meta": {"title": "@width:width @height:height"}},
        "3": {"inputs": {"seed": 0, "steps": 1}, "_meta": {"title": "@seed:seed @steps:steps"}},
    }  # fmt: skip


def test_one_title_can_carry_several_slots() -> None:
    graph = Workflow("keyframe", _knob_graph()).bind(width=480, height=848, steps=6, seed=3)

    assert graph["2"]["inputs"] == {"width": 480, "height": 848}
    assert graph["3"]["inputs"] == {"seed": 3, "steps": 6}


def test_every_part_of_a_title_must_be_a_slot() -> None:
    graph: Graph = {"1": {"inputs": {"seed": 0}, "_meta": {"title": "@seed:seed steps"}}}
    with pytest.raises(WorkflowMismatch, match="each part"):
        Workflow("broken", graph)


def test_supported_keeps_only_the_values_the_graph_has_slots_for() -> None:
    flow = Workflow("animate", _wan_graph())

    assert flow.supported(seed=1, width=480, steps=4) == {"seed": 1}


class RecordingClient:
    def __init__(self) -> None:
        self.graphs: list[Graph] = []

    async def run(self, graph: Graph, *, limit: float) -> list[Output]:
        self.graphs.append(graph)
        return [Output("x.png", "", "output"), Output("x.mp4", "", "output")]

    async def upload(self, image: Path) -> str:
        return image.name

    async def download(self, output: Output, dest: Path) -> Path:
        return dest


async def test_painter_fills_size_and_steps_when_the_graph_has_those_slots(tmp_path: Path) -> None:
    client: Any = RecordingClient()
    painter = ComfyPainter(
        client, Workflow("keyframe", _knob_graph()), width=512, height=896, steps=6
    )

    await painter.paint("a lamp", seed=9, out=tmp_path / "f.png")

    graph = client.graphs[0]
    assert graph["2"]["inputs"] == {"width": 512, "height": 896}
    assert graph["3"]["inputs"] == {"seed": 9, "steps": 6}


async def test_animator_splits_the_steps_between_the_two_experts(tmp_path: Path) -> None:
    wan = _wan_graph()
    wan["57"]["inputs"] |= {"steps": 4, "end_at_step": 2}
    wan["57"]["_meta"]["title"] = "@seed:noise_seed @steps:steps @split:end_at_step"
    wan["58"]["inputs"] |= {"steps": 4, "start_at_step": 2, "end_at_step": 4}
    wan["58"]["_meta"]["title"] = (
        "@seed:noise_seed @steps:steps @split:start_at_step @steps:end_at_step"
    )
    client: Any = RecordingClient()
    animator = ComfyAnimator(client, Workflow("animate", wan), steps=8)

    await animator.animate(
        tmp_path / "f.png", "push in", seconds=2.0, seed=1, out=tmp_path / "c.mp4"
    )

    graph = client.graphs[0]
    assert graph["57"]["inputs"] == {"noise_seed": 1, "steps": 8, "end_at_step": 4}
    assert graph["58"]["inputs"] == {
        "noise_seed": 1,
        "steps": 8,
        "start_at_step": 4,
        "end_at_step": 8,
    }


async def test_a_graph_without_the_optional_slots_still_works(tmp_path: Path) -> None:
    client: Any = RecordingClient()
    animator = ComfyAnimator(client, Workflow("animate-draft", _wan_graph()), steps=8, width=640)

    await animator.animate(
        tmp_path / "f.png", "push in", seconds=2.0, seed=1, out=tmp_path / "c.mp4"
    )

    assert client.graphs[0]["63"]["inputs"] == {"length": 33}


async def test_client_waits_long_and_names_the_error_kind(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        raise httpx.ReadTimeout("slow", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://comfy")
    client = ComfyClient(http)

    with pytest.raises(StageError, match=r"comfy: GET /view: ReadTimeout slow"):
        await client.download(Output("x.mp4", "", "output"), tmp_path / "x.mp4")
    assert seen[0]["read"] == 120
