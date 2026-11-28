"""Runs the whole pipeline on this machine with no models: stand-ins answer for the language
models and the speech service over the same HTTP the real ones speak, and everything else
is real: the command line, the stages, the scene runtime, ffmpeg.

    python scripts/rehearse.py            # the golden episode, start to final.mp4
    python scripts/rehearse.py --beats 4  # a short one, a minute of work

The planner "writes" the golden episode from tests/data, the coder "writes" the safe scene
of each beat, the viewer finds nothing wrong, the narrator reads in silence at the right
pace. What comes out shows that the parts fit together, never how good the models are.

    python scripts/rehearse.py --beats 4 --coder-url http://localhost:8080/v1 --coder NAME

sends the scene code to a real coder model on any OpenAI-compatible server and keeps the
stand-ins for the rest: a way to see how a model reads the scene API before renting a box."""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
import wave
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from reelsmith.scenes import FIXED, fallback
from reelsmith.story import Beat, Episode, Staging
from reelsmith.text import seconds

REPO = Path(__file__).parent.parent
GOLDEN = REPO / "tests" / "data" / "flood-01.json"
RATE = 24000
THINGS = {
    "room": ["bed", "door", "window"],
    "stairwell": ["railing", "door", "wardrobe"],
}
PLAIN = [
    {
        "age": "adult", "build": "average", "skin": "light", "hair": "short",
        "hair_colour": "#3A2A20", "top": "sweater", "top_colour": "#4A6FA5",
        "bottom": "trousers", "bottom_colour": "#2B2F3A", "shoes_colour": "#1A1A1A",
    },
    {
        "age": "adult", "build": "slim", "skin": "light", "hair": "ponytail",
        "hair_colour": "#7A4A2A", "top": "jacket", "top_colour": "#B5533C",
        "bottom": "trousers", "bottom_colour": "#3A3F4A", "shoes_colour": "#22201E",
    },
]  # fmt: skip


def silence(length: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * round(length * RATE))
    return buffer.getvalue()


def heard(audio: bytes, hint: str) -> list[dict[str, Any]]:
    """The words of the hint one after another over the take, each as long as its letters."""
    with wave.open(io.BytesIO(audio)) as w:
        length = w.getnframes() / w.getframerate()
    texts = hint.split()
    step = max(length - 0.3, 0.1) / max(sum(len(t) for t in texts), 1)
    out, t = [], 0.1
    for text in texts:
        out.append({"text": text, "start": round(t, 3), "end": round(t + len(text) * step, 3)})
        t += len(text) * step
    return out


def staged(ep: Episode, beat: Beat) -> Beat:
    if beat.staging:
        return beat
    kind = ep.place(beat.place).kind
    staging = Staging(
        shot="section" if kind == "section" else "wide",
        action="The cast stands; the first of them turns on the middle word.",
        things=THINGS.get(kind, []),
        questions=["Is every character of the beat in the picture?"],
    )
    return beat.model_copy(update={"staging": staging})


class StandIn:
    def __init__(self, ep: Episode, coder_url: str = "") -> None:
        self.coder_url = coder_url.rstrip("/")
        self.ep = ep.model_copy(update={"beats": [staged(ep, b) for b in ep.beats]})

    def answer(self, body: dict[str, Any]) -> str:
        user = body["messages"][-1]["content"]
        if isinstance(user, list):
            user = user[0]["text"]
        shape = body.get("response_format", {}).get("json_schema", {}).get("name")
        if not shape and self.coder_url:
            return self._real(body)
        made = getattr(self, f"_{shape}".lower(), None) if shape else self._code
        if made is None:
            raise KeyError(f"the rehearsal has no answer of the shape {shape}")
        return str(made(user))

    def _real(self, body: dict[str, Any]) -> str:
        """The answer of the real coder at `coder_url`, to the request as it came."""
        request = urllib.request.Request(
            f"{self.coder_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            return str(json.load(response)["choices"][0]["message"]["content"])

    def _outline(self, _: str) -> str:
        ep = self.ep
        return json.dumps(
            {
                "title": ep.title,
                "premise": ep.premise,
                "characters": [c.model_dump(exclude={"card"}) for c in ep.characters],
                "hero": ep.characters[0].key,
                "want": "what the hero wants",
                "obstacle": "what stands in the way",
                "places": [p.model_dump() for p in ep.places],
                "beats": [b.lines[0] for b in ep.beats],
                "planted": "the detail the ending brings back",
                "ending": ep.ending,
                "narration": " ".join(b.text for b in ep.beats),
                "stakes_line": ep.beats[0].lines[0],
                "turn_line": ep.beats[-1].lines[-1],
            }
        )

    def _heard(self, _: str) -> str:
        hero = self.ep.characters[0].name
        return json.dumps({"hero": hero, "wants": "to live", "danger": "the water", "story": "…"})

    def _cut(self, _: str) -> str:
        ep = self.ep
        return json.dumps(
            {
                "hook": ep.hook,
                "hud": ep.hud,
                "beats": [b.model_dump(exclude={"staging"}) for b in ep.beats],
                "cliffhanger": ep.cliffhanger,
                "music": ep.music or "slow dark ambient",
            }
        )

    def _cast(self, _: str) -> str:
        cards = [
            {"key": c.key, "card": c.card.model_dump() if c.card else PLAIN[i % len(PLAIN)]}
            for i, c in enumerate(self.ep.characters)
        ]
        return json.dumps({"cards": cards})

    def _direction(self, _: str) -> str:
        return json.dumps({"beats": [b.staging.model_dump() for b in self.ep.beats if b.staging]})

    def _looked(self, user: str) -> str:
        questions = re.findall(r"^\d+\. (.+)$", user, re.MULTILINE)
        answers = [{"question": q, "yes": q != FIXED[0], "why": "rehearsal"} for q in questions]
        return json.dumps({"answers": answers})

    def _sheet(self, user: str) -> str:
        """A plain sheet: the staging's things at the walls, the cast between them, the first
        of them turning to the first thing on a word in the middle."""
        lines = re.search(r"^Lines: (.+)$", user, re.MULTILINE)
        beat = next(b for b in self.ep.beats if lines and b.text == lines.group(1))
        names = [t for t in (beat.staging.things if beat.staging else []) if t != "water"]
        things = [
            {"name": name, "where": where}
            for name, where in zip(names, ["far_left", "far_right", "centre"], strict=False)
        ]
        people = [
            {"who": key, "where": where}
            for key, where in zip(beat.cast, ["left", "right", "centre"], strict=False)
        ]
        said = beat.text.split()
        word = said[len(said) // 2].strip(".,!?:;«»—")
        acts = [
            {"on_word": word, "who": people[0]["who"], "does": "look", "what": things[0]["name"]}
            for _ in [0]
            if people and things
        ]
        camera = [
            {"on_word": word, "move": "push", "to": p["who"], "zoom": 1.05} for p in people[:1]
        ]
        return json.dumps({"things": things, "people": people, "acts": acts, "camera": camera})

    def _code(self, user: str) -> str:
        lines = re.search(r"^Lines: (.+)$", user, re.MULTILINE)
        beat = next(b for b in self.ep.beats if lines and b.text == lines.group(1))
        code = fallback(beat, self.ep.place(beat.place).kind, {})
        return f"The scene of this beat.\n```js\n{code}\n```"


def handler(stand_in: StandIn) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def _send(self, status: int, kind: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.endswith("/chat/completions"):
                try:
                    content = stand_in.answer(json.loads(raw))
                except (KeyError, StopIteration, OSError) as exc:
                    self._send(500, "text/plain", str(exc).encode())
                    return
                reply = {"choices": [{"message": {"role": "assistant", "content": content}}]}
                self._send(200, "application/json", json.dumps(reply).encode())
            elif self.path == "/speak":
                text = json.loads(raw)["text"]
                self._send(200, "audio/wav", silence(seconds(text)))
            elif self.path == "/words":
                head = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
                parts: dict[str, bytes] = {}
                for part in message_from_bytes(head + raw).walk():
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        parts[str(part.get_param("name", header="content-disposition"))] = payload
                words = heard(parts["audio"], parts["hint"].decode())
                self._send(200, "application/json", json.dumps(words).encode())
            elif self.path == "/unload":
                self._send(204, "text/plain", b"")
            else:
                self._send(404, "text/plain", b"unknown")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--beats", type=int, default=0, help="only the first beats; 0 is all")
    parser.add_argument("--jobs", type=Path, default=REPO / "review" / "rehearsal")
    parser.add_argument(
        "--coder-url",
        default="",
        help="a real coder behind an OpenAI-compatible API, such as http://localhost:8080/v1; "
        "the scenes are then written by it, everything else stays a stand-in",
    )
    parser.add_argument("--coder", default="", help="the model's name on that server")
    args = parser.parse_args()
    ep = Episode.model_validate_json(GOLDEN.read_text(encoding="utf-8"))
    if args.beats:
        ep = ep.model_copy(update={"beats": ep.beats[: max(args.beats, 4)]})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(StandIn(ep, args.coder_url)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    env = os.environ | {
        "REELSMITH_LLM_URL": f"{url}/v1",
        "REELSMITH_SPEECH_URL": url,
        "REELSMITH_VOICE_URL": url,
        "REELSMITH_JOBS": str(args.jobs),
        "REELSMITH_OUTBOX": str(args.jobs / "outbox"),
        "REELSMITH_EDITOR": "",
        "REELSMITH_VARIANTS": "1",
    }
    if args.coder:
        env["REELSMITH_CODER"] = args.coder
    command = [sys.executable, "-c", "from reelsmith.cli import app; app()"]
    before = set(args.jobs.glob("*/job.json"))
    subprocess.run([*command, "add", ep.premise], env=env, cwd=REPO, check=True)
    subprocess.run([*command, "run"], env=env, cwd=REPO, check=True)
    server.shutdown()
    (job,) = set(args.jobs.glob("*/job.json")) - before
    status = json.loads(job.read_text(encoding="utf-8"))["status"]
    final = job.parent / "final.mp4"
    print(f"{status}: {final}" if final.is_file() else f"{status}: no video, see {job}")
    sys.exit(0 if status == "assembled" else 1)


if __name__ == "__main__":
    main()
