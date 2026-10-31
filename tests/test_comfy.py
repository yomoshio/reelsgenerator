import pytest

from reelsmith.services.comfy import Graph, Workflow, WorkflowMismatch, wan_length


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
