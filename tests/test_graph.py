import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from reelsmith import graph
from reelsmith.jobs import Context, Job, JobError, Jobs, Stage, Status
from tests.fakes import REPO

RAN: list[str] = []


def _steps(fail: str = "") -> list[Stage]:
    def step(name: str):  # type: ignore[no-untyped-def]
        async def run(job: Job, folder: Path, ctx: Context) -> None:
            if name == fail:
                raise RuntimeError("the model is away")
            RAN.append(f"{name}:{ctx.settings.tts}")
            (folder / {"write": "episode.json", "voice": "voice"}[name]).write_text("{}")

        return run

    return [
        Stage("write", Status.NEW, Status.WRITTEN, step("write")),
        Stage("voice", Status.WRITTEN, Status.VOICED, step("voice")),
    ]


def _settings(tmp_path: Path, **more: object):  # type: ignore[no-untyped-def]
    return graph.settings(REPO, jobs=tmp_path / "jobs", **more)


def test_the_same_idea_twice_is_one_job(tmp_path: Path) -> None:
    made = _settings(tmp_path)
    first = graph.job_for(made, "Свет гаснет на 32 этаже.", "blackout")
    again = graph.job_for(made, "  Свет гаснет на 32 этаже.\n", "blackout")
    other = graph.job_for(made, "Вода поднимается.", "blackout")
    assert first.id == again.id != other.id
    with pytest.raises(JobError):
        graph.job_for(made, "  ")


def test_settings_read_the_folder_they_are_given(tmp_path: Path) -> None:
    made = _settings(tmp_path, tts="qwen", planner="")
    assert made.styles == REPO / "styles"
    assert made.runtime.is_absolute()
    assert made.tts == "qwen"
    assert made.planner


async def test_a_step_runs_once_and_again_only_when_its_settings_change(tmp_path: Path) -> None:
    RAN.clear()
    made = _settings(tmp_path, tts="qwen")
    job = graph.job_for(made, "Свет гаснет.", "blackout")
    with pytest.raises(JobError, match="write step first"):
        await graph.advance(made, job.id, "voice", _steps())
    await graph.advance(made, job.id, "write", _steps())
    await graph.advance(made, job.id, "voice", _steps())
    await graph.advance(made, job.id, "write", _steps())
    after = await graph.advance(made, job.id, "voice", _steps())
    assert RAN == ["write:qwen", "voice:qwen"]
    assert after.status == Status.VOICED

    other = _settings(tmp_path, tts="chatterbox")
    await graph.advance(other, job.id, "write", _steps())
    await graph.advance(other, job.id, "voice", _steps())
    assert RAN == ["write:qwen", "voice:qwen", "voice:chatterbox"]
    folder = Jobs(made.jobs).folder(job)
    assert set(json.loads((folder / "graph.json").read_text())) == {"write", "voice"}


async def test_a_step_that_fails_says_why_and_can_be_run_again(tmp_path: Path) -> None:
    RAN.clear()
    made = _settings(tmp_path)
    job = graph.job_for(made, "Свет гаснет.", "blackout")
    with pytest.raises(JobError, match=r"write failed.*the model is away"):
        await graph.advance(made, job.id, "write", _steps(fail="write"))
    assert Jobs(made.jobs).get(job.id).error
    done = await graph.advance(made, job.id, "write", _steps())
    assert done.status == Status.WRITTEN
    assert done.error is None


def _nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """The node pack, loaded as ComfyUI would load it, with ComfyUI's own module stood in."""
    paths = types.ModuleType("folder_paths")
    paths.get_output_directory = lambda: str(tmp_path / "output")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "folder_paths", paths)
    monkeypatch.setenv("REELSMITH_ROOT", str(REPO))
    spec = importlib.util.spec_from_file_location(
        "reelsmith_nodes", REPO / "comfyui" / "reelsmith_nodes" / "__init__.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_node_declares_what_comfyui_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = _nodes(tmp_path, monkeypatch)
    assert set(nodes.NODE_CLASS_MAPPINGS) == set(nodes.NODE_DISPLAY_NAME_MAPPINGS)
    for made in nodes.NODE_CLASS_MAPPINGS.values():
        assert "required" in made.INPUT_TYPES()
        assert callable(getattr(made, made.FUNCTION))
        assert len(made.RETURN_TYPES) == len(made.RETURN_NAMES)
    assert "blackout" in nodes.Idea.INPUT_TYPES()["required"]["style"][0]


def test_an_idea_node_gives_a_job_and_the_preview_shows_its_keyframes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = _nodes(tmp_path, monkeypatch)
    options = nodes.Settings().run(tts="qwen", staging="sheet", root=str(REPO), planner="")[0]
    options["jobs"] = tmp_path / "jobs"
    (job,) = nodes.Idea().run("Свет гаснет.", "blackout", options)
    keys = tmp_path / "jobs" / job / "keys"
    keys.mkdir()
    (keys / "beat01-1.png").write_bytes(b"png")
    shown = nodes.Preview().run(job, options)
    assert shown["result"][0] == ""
    assert shown["ui"]["images"] == [
        {"filename": f"{job}-beat01-1.png", "subfolder": "reelsmith", "type": "output"}
    ]
    assert (tmp_path / "output" / "reelsmith" / f"{job}-beat01-1.png").is_file()


async def test_a_stage_node_moves_the_job_on_without_blocking_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = _nodes(tmp_path, monkeypatch)
    options = {"root": str(REPO), "jobs": tmp_path / "jobs"}
    (job,) = nodes.Idea().run("Свет гаснет.", "blackout", options)
    asked: list[str] = []

    async def advance(made: object, job_id: str, step: str) -> None:
        asked.append(step)

    monkeypatch.setattr(nodes.graph, "advance", advance)
    assert await nodes.Film().run(job, options) == (job,)
    assert asked == ["write", "voice", "stage", "render", "assemble"]
