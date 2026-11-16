import json
import shutil
import subprocess
from collections import namedtuple
from pathlib import Path

import pytest

from reelsmith import assemble, render, scenes
from reelsmith.captions import Word
from reelsmith.jobs import Jobs, Source
from reelsmith.story import Card, Episode
from reelsmith.styles import Styles
from tests.fakes import DATA, REPO, FakeLlm, context, wav

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None
    or shutil.which("ffmpeg") is None
    or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="rendering needs node, ffmpeg and `npm ci` in runtime/",
)
STYLE = Styles(REPO / "styles").get("blackout")
CARD = Card(age="adult", build="average", skin="light", hair="short", hair_colour="#222222",
            top="raincoat", top_colour="#2E4A70", bottom="trousers", bottom_colour="#1C2230",
            shoes_colour="#101014")  # fmt: skip


def _length(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout)


def _job(tmp_path: Path, beats: int, seconds: float = 1.2):  # type: ignore[no-untyped-def]
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    people = [c.model_copy(update={"card": CARD}) for c in ep.characters]
    ep = ep.model_copy(update={"beats": ep.beats[:beats], "characters": people})
    ctx = context(
        tmp_path, FakeLlm(), runtime=REPO / "runtime", library=tmp_path / "lib", workers=4
    )
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="x"), "blackout")
    folder = jobs.folder(job)
    (folder / "episode.json").write_text(ep.model_dump_json())
    for d in ("voice", "scenes"):
        (folder / d).mkdir()
    timing = []
    for n, beat in enumerate(ep.beats, 1):
        (folder / "voice" / f"beat{n:02d}.wav").write_bytes(wav(seconds - 0.35))
        said = beat.text.split()
        step = (seconds - 0.5) / len(said)
        timing.append(
            {
                "seconds": seconds,
                "words": [
                    {"text": w, "start": 0.1 + i * step, "end": 0.1 + (i + 1) * step}
                    for i, w in enumerate(said)
                ],
            }
        )
        code = scenes.fallback(beat, ep.place(beat.place).kind, {})
        (folder / "scenes" / f"beat{n:02d}.js").write_text(code)
    (folder / "voice" / "timing.json").write_text(json.dumps({"beats": timing}))
    return ctx, job, folder, ep


async def test_a_beat_clip_runs_as_long_as_its_voice(tmp_path: Path) -> None:
    ctx, _, folder, ep = _job(tmp_path, 1)
    timing = scenes.timings(folder)[0]
    clip = await render.render_beat(ctx.settings, STYLE, ep, 0, timing=timing, folder=folder)
    assert abs(_length(clip) - 1.2) <= 1 / 30 + 0.03


async def test_the_episode_is_the_beats_joined_with_the_closing_card(tmp_path: Path) -> None:
    ctx, job, folder, ep = _job(tmp_path, 3)
    await render.render(job, folder, ctx)
    assert sorted(p.name for p in (folder / "clips").glob("*.mp4")) == [
        "beat01.mp4",
        "beat02.mp4",
        "beat03.mp4",
    ]
    await assemble.assemble(job, folder, ctx)
    expected = 3 * 1.2 + assemble.CARD_SECONDS - 3 * assemble.JOIN
    assert abs(_length(folder / "final.mp4") - expected) < 0.15
    assert not list((folder / "clips").glob("*.mp4"))
    assert (folder / "check.json").is_file()
    assert (folder / "post.txt").read_text().startswith(ep.title)


async def test_render_refuses_to_start_on_a_full_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, job, folder, _ = _job(tmp_path, 1)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(render.shutil, "disk_usage", lambda _: usage(100e9, 99e9, 1e9))
    with pytest.raises(render.RenderError, match=r"only 1.0 GB free"):
        await render.render(job, folder, ctx)


def test_words_that_bring_up_plates_are_stressed() -> None:
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    beat = ep.beats[0]
    words = [Word(w, i, i + 0.5) for i, w in enumerate(beat.text.split())]
    stressed = [w.text for w in render.accented(beat, words) if w.accent]
    assert stressed
    assert all(any(r.on_word.lower() in w.lower() for r in beat.reveals) for w in stressed)
