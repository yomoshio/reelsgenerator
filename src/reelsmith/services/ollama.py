"""The local LLM on Ollama: writes the script, criticises it, and judges pictures.

The reply's JSON schema goes in `format`, so Ollama constrains decoding and the answer
parses straight into the model. Stills go as base64 `images`, so the judge model must be
one that takes pictures."""

import asyncio
import base64
import math
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from reelsmith.books import numbered
from reelsmith.checks import language_name
from reelsmith.models import Adaptation, Outline, Retelling, Script, Season, StageError, Verdict
from reelsmith.styles import Style

PATCH = 32  # a Qwen-VL image token covers 32 x 32 pixels; other judges spend fewer
SPARE = 4096  # tokens kept beside the images for the prompt and the answer
NARROWEST = 256


def _prompt(name: str) -> str:
    return resources.files("reelsmith.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


def fill(template: str, **values: object) -> str:
    """Plain substitution of `{name}` placeholders; the prompts contain other braces."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


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
        writer_temperature: float = 0.8,
        critic_temperature: float = 0.2,
        judge_temperature: float = 0.1,
        context: int = 12288,
    ) -> None:
        self._http = http
        self._writer = writer_model
        self._judge = judge_model
        self._keep_alive = keep_alive
        self._language = language_name(language)
        self._heat = (writer_temperature, critic_temperature, judge_temperature)
        self._context = context

    def widest(self, count: int) -> int:
        """The widest 9:16 still of which `count` fit the context beside the prompt. The
        judge sees every shot of the cut at once, and Ollama refuses a request longer than
        the context: 26 stills 720 wide take 23,000 tokens."""
        per_image = max(self._context - SPARE, 0) / max(count, 1)
        side = math.isqrt(int(per_image * 9 / 16))
        while side > 1 and side * math.ceil(side * 16 / 9) > per_image:
            side -= 1
        return max(side * PATCH, NARROWEST)

    async def plan(self, idea: str, style: Style) -> Outline:
        story = style.story
        system = fill(
            _prompt("planner"),
            brief=story.brief.strip(),
            seconds=f"{story.seconds[0]} to {story.seconds[1]}",
            beats=f"{story.beats[0]} to {story.beats[1]}",
            language=self._language,
        )
        return await self._chat(self._writer, system, idea, Outline, temperature=self._heat[0])

    async def season(self, synopsis: str, style: Style, episodes: int) -> Season:
        story = style.story
        system = fill(
            _prompt("season"),
            brief=story.brief.strip(),
            seconds=f"{story.seconds[0]} to {story.seconds[1]}",
            episodes=episodes,
            language=self._language,
        )
        return await self._chat(self._writer, system, synopsis, Season, temperature=self._heat[0])

    async def retell(self, passage: str) -> list[str]:
        system = fill(_prompt("retell"), language=self._language)
        told = await self._chat(self._writer, system, passage, Retelling, temperature=self._heat[1])
        return told.events

    async def adapt(self, events: list[str], style: Style, most: int) -> Adaptation:
        story = style.story
        system = fill(
            _prompt("adapt"),
            brief=story.brief.strip(),
            seconds=f"{story.seconds[0]} to {story.seconds[1]}",
            most=most,
            language=self._language,
        )
        return await self._chat(
            self._writer, system, numbered(events), Adaptation, temperature=self._heat[0]
        )

    async def write(self, idea: str, style: Style, notes: str | None = None) -> Script:
        ask = idea if notes is None else f"{idea}\n\nRewrite the script. The critic said: {notes}"
        return await self._chat(
            self._writer, self._writer_prompt(style), ask, Script, temperature=self._heat[0]
        )

    async def review(self, script: Script, style: Style, outline: str = "") -> Verdict:
        draft = script.model_dump_json(indent=2)
        system = fill(
            _prompt("critic"),
            brief=style.story.brief.strip(),
            outline=outline or "none: judge the script on its own",
            criteria=style.story.critic.strip(),
            words=style.story.words,
            language=self._language,
            kinds=", ".join(style.overlays) or "none",
        )
        return await self._chat(self._writer, system, draft, Verdict, temperature=self._heat[1])

    async def pick(self, brief: str, images: list[Path], style: Style) -> int:
        ask = (
            f"Pick the frame that best shows: {brief}. "
            f"Answer with its index, counting from 0 to {len(images) - 1}."
        )
        system = self._eye(style)
        chosen = await self._chat(
            self._judge, system, ask, Pick, images=images, temperature=self._heat[2]
        )
        return min(max(chosen.index, 0), len(images) - 1)

    async def inspect(self, motion: str, stills: list[Path], style: Style) -> Verdict:
        ask = f"Inspect this clip. It should show: {motion}."
        return await self._chat(
            self._judge, self._eye(style), ask, Verdict, images=stills, temperature=self._heat[2]
        )

    async def judge(self, script: Script, stills: list[Path], style: Style) -> Verdict:
        looks = "\n".join(f"- {c.name}: {c.look}" for c in script.characters)
        shots = "\n".join(f"Image {i} is shot {i}: {s.picture}" for i, s in enumerate(script.shots))
        ask = f"Review the finished cut. The characters:\n{looks}\n\nThe images:\n{shots}"
        return await self._chat(
            self._judge, self._eye(style), ask, Verdict, images=stills, temperature=self._heat[2]
        )

    def _writer_prompt(self, style: Style) -> str:
        story = style.story
        return fill(
            _prompt("writer"),
            brief=story.brief.strip(),
            language=self._language,
            seconds=f"{story.seconds[0]} to {story.seconds[1]}",
            shots=f"{story.shots[0]} to {story.shots[1]}",
            words=story.words,
            overlays=style.menu(),
        )

    def _eye(self, style: Style) -> str:
        return fill(_prompt("judge"), look=style.look.judge.strip())

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
        temperature: float,
    ) -> T:
        message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            message["images"] = await asyncio.to_thread(_encoded, images)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, message],
            "format": shape.model_json_schema(),
            "think": False,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": temperature, "num_ctx": self._context},
        }
        try:
            reply = await self._http.post("/api/chat", json=body, timeout=300)
            reply.raise_for_status()
            return shape.model_validate_json(reply.json()["message"]["content"])
        except httpx.HTTPError as exc:
            raise StageError(f"ollama: {type(exc).__name__} {exc}".strip()) from exc
        except ValidationError as exc:
            raise StageError(
                f"ollama: {shape.__name__} does not match schema: {exc.error_count()} errors"
            ) from exc
