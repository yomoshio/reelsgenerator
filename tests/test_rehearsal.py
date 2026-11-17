import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from reelsmith.story import Episode
from tests.fakes import DATA, REPO

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


def test_scene_code_goes_to_a_real_coder_when_one_is_named() -> None:
    spec = importlib.util.spec_from_file_location("rehearse", REPO / "scripts" / "rehearse.py")
    assert spec is not None
    assert spec.loader is not None
    rehearse = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearse)
    asked: list[dict[str, object]] = []

    class Coder(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def do_POST(self) -> None:
            asked.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": {"content": "```js\nreal\n```"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Coder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ep = Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))
    stand_in = rehearse.StandIn(ep, f"http://127.0.0.1:{server.server_port}/v1")
    request = {"model": "m", "messages": [{"role": "user", "content": "Lines: x"}]}
    try:
        assert "real" in stand_in.answer(request)
        shaped = request | {"response_format": {"json_schema": {"name": "Cast"}}}
        assert "cards" in stand_in.answer(shaped)
    finally:
        server.shutdown()
    assert asked == [request]
