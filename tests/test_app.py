import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from reelsmith import app
from reelsmith.models import Recipe, StageError, Status
from reelsmith.pipeline import Gates
from reelsmith.settings import Settings
from tests.fakes import REPO_STYLES, FakeAnalytics, services

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")


def _graph(*slots: tuple[str, str]) -> str:
    return json.dumps(
        {
            str(i): {
                "class_type": "N",
                "inputs": {field: 0},
                "_meta": {"title": f"@{name}:{field}"},
            }
            for i, (name, field) in enumerate(slots)
        }
    )


def _export(folder: Path, *names: str) -> None:
    graphs = {
        "keyframe.json": _graph(("prompt", "text"), ("seed", "seed")),
        "animate.json": _graph(
            ("image", "image"), ("prompt", "text"), ("length", "length"), ("seed", "seed")
        ),
        "animate-draft.json": _graph(
            ("image", "image"), ("prompt", "text"), ("length", "length"), ("seed", "seed")
        ),
        "animate-hd.json": _graph(
            ("image", "image"), ("prompt", "text"), ("length", "length"), ("seed", "seed")
        ),
        "score.json": _graph(("tags", "tags"), ("seconds", "seconds"), ("seed", "seed")),
    }
    for name in names:
        (folder / name).write_text(graphs[name])


async def test_local_services_need_the_three_graphs_and_offer_the_draft_when_exported(
    tmp_path: Path,
) -> None:
    settings = Settings(workflows=tmp_path, styles=REPO_STYLES)
    _export(tmp_path, "keyframe.json", "animate.json")

    async with httpx.AsyncClient() as http:
        with pytest.raises(FileNotFoundError, match=r"score\.json"):
            app.local_services(settings, ollama=http, comfy=http, tts=http)

        _export(tmp_path, "score.json")
        built, tenants = app.local_services(settings, ollama=http, comfy=http, tts=http)
        assert set(built.animators) == {"still", "wan-2.2"}
        assert set(tenants) == {"llm", "comfy", "tts"}
        with pytest.raises(StageError, match="wan-5b"):
            built.check(Recipe(video="wan-5b"))

        _export(tmp_path, "animate-draft.json", "animate-hd.json")
        built, _ = app.local_services(settings, ollama=http, comfy=http, tts=http)
        assert set(built.animators) == {"still", "wan-2.2", "wan-2.2-hd", "wan-5b"}
        built.check(Recipe(video="wan-5b", hook_video="wan-2.2"))


async def test_settings_from_env_reach_the_gates_and_the_montage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REELSMITH_CLIP_PASS", "5.5")
    monkeypatch.setenv("REELSMITH_CANDIDATES", "1")
    monkeypatch.setenv("REELSMITH_MUSIC_LEVEL", "0.3")
    settings = Settings(workflows=tmp_path, styles=REPO_STYLES)
    _export(tmp_path, "keyframe.json", "animate.json", "score.json")

    async with httpx.AsyncClient() as http:
        built, _ = app.local_services(settings, ollama=http, comfy=http, tts=http)

    assert built.gates == Gates(clip_pass=5.5, candidates=1)
    assert built.montage.music_level == 0.3


def test_sizes_that_the_models_cannot_take_are_refused() -> None:
    with pytest.raises(ValueError, match="multiple of 16"):
        Settings(clip_width=500)


def test_stages_for_keeps_the_order_and_drops_measure_without_analytics(tmp_path: Path) -> None:
    plain, measured = services(tmp_path), services(tmp_path, analytics=FakeAnalytics())

    assert [s.name for s in app.stages_for(plain)] == [
        "write", "voice", "paint", "pick", "animate", "check", "score", "assemble", "publish"
    ]  # fmt: skip
    assert app.stages_for(measured)[-1].name == "measure"
    assert [s.name for s in app.stages_for(plain, ["paint", "Voice"])] == ["voice", "paint"]
    with pytest.raises(ValueError, match="qa"):
        app.stages_for(plain, ["qa"])


@needs_ffmpeg
async def test_demo_runs_both_arms_to_the_end(tmp_path: Path) -> None:
    arm_a = Recipe(video="wan-2.2")

    result = await app.demo(
        ["зомби в метро", "маяк"],
        arm_a=arm_a,
        arm_b=Recipe(video="wan-5b"),
        out=tmp_path,
        styles=REPO_STYLES,
    )

    arms: dict[str, Any] = {a.name: a for a in result.arms}
    assert set(arms) == {"A", "B"}
    assert (arms["A"].videos, arms["B"].videos) == (2, 2)
    assert {j.status for j in result.jobs} <= {Status.MEASURED, Status.FAILED}
    assert result.report.good >= 1
    assert result.report.cost_per_good is not None
    assert {j.recipe.video for j in result.jobs if j.arm == "B"} == {"wan-5b"}
    assert len(list((tmp_path / "outbox").iterdir())) == result.report.good
    assert all(j.rating is not None for j in result.jobs if j.good)
