import json
from pathlib import Path
from typing import Any

import httpx

from reelsmith.services.voxcpm import VoxNarrator


async def test_the_narrator_sends_the_line_its_delivery_and_the_voice_settings(
    tmp_path: Path,
) -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://tts")
    narrator = VoxNarrator(http, "narrator", cfg=1.8, steps=20)

    out = await narrator.speak("Свет гаснет.", tmp_path / "v.wav", delivery="a tense whisper")

    assert out.read_bytes() == b"RIFF"
    assert seen == [
        {
            "text": "Свет гаснет.",
            "control": "a tense whisper",
            "voice": "narrator",
            "cfg": 1.8,
            "steps": 20,
        }
    ]
