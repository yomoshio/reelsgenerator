import asyncio
from pathlib import Path

import httpx

from reelsmith.models import StageError


class VoxNarrator:
    """Client for services/tts, a thin HTTP wrapper around VoxCPM2."""

    name = "voxcpm"
    suffix = ".wav"

    def __init__(
        self, http: httpx.AsyncClient, voice: str, *, cfg: float = 2.0, steps: int = 10
    ) -> None:
        self._http = http
        self._request = {"voice": voice, "cfg": cfg, "steps": steps}

    async def speak(self, text: str, out: Path, voice: str | None = None) -> Path:
        body = {"text": text, **self._request} | ({"voice": voice} if voice else {})
        try:
            reply = await self._http.post("/speak", json=body, timeout=300)
            reply.raise_for_status()
        except httpx.HTTPError as exc:
            raise StageError(f"tts: {type(exc).__name__} {exc}".strip()) from exc
        await asyncio.to_thread(out.write_bytes, reply.content)
        return out

    async def release(self) -> None:
        reply = await self._http.post("/unload", timeout=30)
        reply.raise_for_status()
