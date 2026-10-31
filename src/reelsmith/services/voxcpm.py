import asyncio
from pathlib import Path

import httpx

from reelsmith.models import StageError


class VoxNarrator:
    """Client for services/tts, a thin HTTP wrapper around VoxCPM2."""

    name = "voxcpm"
    suffix = ".wav"

    def __init__(self, http: httpx.AsyncClient, voice: str) -> None:
        self._http = http
        self._voice = voice

    async def speak(self, text: str, out: Path) -> Path:
        try:
            reply = await self._http.post(
                "/speak", json={"text": text, "voice": self._voice}, timeout=120
            )
            reply.raise_for_status()
        except httpx.HTTPError as exc:
            raise StageError(f"tts: {exc}") from exc
        await asyncio.to_thread(out.write_bytes, reply.content)
        return out

    async def release(self) -> None:
        reply = await self._http.post("/unload", timeout=30)
        reply.raise_for_status()
