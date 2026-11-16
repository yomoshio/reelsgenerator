import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fakes import REPO

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None
    or shutil.which("ffmpeg") is None
    or not (REPO / "runtime" / "node_modules").is_dir(),
    reason="the rehearsal needs node, ffmpeg and `npm ci` in runtime/",
)


def test_an_idea_becomes_a_video_through_the_command_line(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "scripts/rehearse.py", "--beats", "4", "--jobs", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    (job,) = tmp_path.glob("*/job.json")
    assert json.loads(job.read_text(encoding="utf-8"))["status"] == "assembled"
    assert (job.parent / "final.mp4").stat().st_size > 100_000
    assert not list((job.parent / "clips").glob("*.mp4"))
    reports = [json.loads(p.read_text()) for p in (job.parent / "scenes").glob("beat*.json")]
    assert len(reports) == 4
    assert not any(r["fallback"] or r["left"] for r in reports)
