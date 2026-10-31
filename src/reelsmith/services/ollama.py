"""The local LLM on Ollama: writes the script, criticises it, and judges pictures.

The reply's JSON schema goes in `format`, so Ollama constrains decoding and the answer
parses straight into the model. Stills go as base64 `images`, so the judge model must be
one that takes pictures."""

import asyncio
import base64
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from reelsmith.models import Script, StageError, Verdict


def _prompt(name: str) -> str:
    return resources.files("reelsmith.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


def _encoded(images: Sequence[Path]) -> list[str]:
    return [base64.b64encode(p.read_bytes()).decode() for p in images]


class Pick(BaseModel):
    index: int


class OllamaLlm:
    """Writer and critic run on `writer_model`, the judge on `judge_model`; the two may be
    the same tag, and then only one model is ever loaded."""

    name = "ollama"

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        writer_model: str,
        judge_model: str,
        language: str,
        keep_alive: str = "15m",
    ) -> None:
        self._http = http
        self._writer = writer_model
        self._judge = judge_model
        self._keep_alive = keep_alive
        self._brief = _prompt("writer").replace("{language}", language)
        self._critic = _prompt("critic")
        self._eye = _prompt("judge")

    async def write(self, idea: str, notes: str | None = None) -> Script:
        ask = idea if notes is None else f"{idea}\n\nRewrite the script. The critic said: {notes}"
        return await self._chat(self._writer, self._brief, ask, Script)

    async def review(self, script: Script) -> Verdict:
        draft = script.model_dump_json(indent=2)
        return await self._chat(self._writer, self._critic, draft, Verdict, temperature=0.2)

    async def pick(self, brief: str, images: list[Path]) -> int:
        ask = (
            f"Pick the frame that best shows: {brief}. "
            f"Answer with its index, counting from 0 to {len(images) - 1}."
        )
        chosen = await self._chat(self._judge, self._eye, ask, Pick, images=images, temperature=0.1)
        return min(max(chosen.index, 0), len(images) - 1)

    async def inspect(self, motion: str, stills: list[Path]) -> Verdict:
        ask = f"Inspect this clip. It should show: {motion}."
        return await self._chat(
            self._judge, self._eye, ask, Verdict, images=stills, temperature=0.1
        )

    async def judge(self, script: Script, stills: list[Path]) -> Verdict:
        ask = f"Review the finished cut against its script:\n{script.model_dump_json(indent=2)}"
        return await self._chat(
            self._judge, self._eye, ask, Verdict, images=stills, temperature=0.1
        )

    async def release(self) -> None:
        """Unloads whatever the server holds: the card must be free for the next stage."""
        loaded = (await self._http.get("/api/ps", timeout=30)).json().get("models", [])
        for model in loaded:
            body = {"model": model["name"], "keep_alive": 0}
            reply = await self._http.post("/api/generate", json=body, timeout=60)
            reply.raise_for_status()

    async def _chat[T: BaseModel](
        self,
        model: str,
        system: str,
        user: str,
        shape: type[T],
        *,
        images: Sequence[Path] = (),
        temperature: float = 0.8,
    ) -> T:
        message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            message["images"] = await asyncio.to_thread(_encoded, images)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, message],
            "format": shape.model_json_schema(),
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": temperature, "num_ctx": 8192},
        }
        try:
            reply = await self._http.post("/api/chat", json=body, timeout=300)
            reply.raise_for_status()
            return shape.model_validate_json(reply.json()["message"]["content"])
        except httpx.HTTPError as exc:
            raise StageError(f"ollama: {exc}") from exc
        except ValidationError as exc:
            raise StageError(
                f"ollama: {shape.__name__} does not match schema: {exc.error_count()} errors"
            ) from exc
