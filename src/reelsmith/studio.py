"""The worker's side of the ComfyUI blocks: requests they drop into studio/inbox, and the
status file they read. Runs between conveyor turns, so it never competes with a stage."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from reelsmith.models import Job, Recipe, StageError, Status
from reelsmith.pipeline import showcase_name
from reelsmith.series import Serial, ideas, write_serial
from reelsmith.store import Store
from reelsmith.styles import Style, Styles

log = structlog.get_logger()

ANIMATION: dict[str, dict[str, str | None]] = {
    "hybrid": {"video": "wan-2.2", "calm_video": "still", "hook_video": None},
    "still": {"video": "still", "calm_video": None, "hook_video": None},
    "wan": {"video": "wan-2.2", "calm_video": None, "hook_video": None},
    "wan-hd": {"video": "wan-2.2-hd", "calm_video": None, "hook_video": None},
}
STATUS_ROWS = 15

MakeSerial = Callable[[str, Style, int], Awaitable[Serial]]


class Studio:
    def __init__(
        self,
        folder: Path,
        store: Store,
        *,
        recipe: Recipe,
        styles: Styles,
        make_serial: MakeSerial,
        before_llm: Callable[[], Awaitable[None]],
    ) -> None:
        self.folder = folder
        self._store = store
        self._recipe = recipe
        self._styles = styles
        self._make_serial = make_serial
        self._before_llm = before_llm

    @property
    def paused(self) -> bool:
        return (self.folder / "paused").exists()

    async def sync(self) -> bool:
        """Takes the requests and writes the status; False while the conveyor is paused."""
        await self.take()
        await self.write_status()
        return not self.paused

    async def take(self) -> None:
        inbox = self.folder / "inbox"
        done = inbox / "done"
        done.mkdir(parents=True, exist_ok=True)
        for path in sorted(inbox.glob("*.json")):
            try:
                answer = await self._handle(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, KeyError, LookupError, StageError) as exc:
                answer = f"error: {exc}"
            path.rename(done / path.name)
            (done / f"{path.stem}.txt").write_text(answer + "\n", encoding="utf-8")
            log.info("studio.request", file=path.name, answer=answer)

    async def write_status(self) -> None:
        jobs = (await self._store.find())[-STATUS_ROWS:]
        lines = ["Конвейер на паузе.", ""] if self.paused else []
        lines.append("id        статус     попытки  идея")
        for job in reversed(jobs):
            idea = job.idea if len(job.idea) <= 60 else job.idea[:59] + "…"
            lines.append(f"{job.id.hex[:8]}  {job.status.value:<9}  {job.attempts:<7}  {idea}")
            if job.status is Status.ASSEMBLED:
                lines.append(f"          ролик: reelsmith/videos/{showcase_name(job)}")
            if job.status is Status.FAILED and job.last_error:
                lines.append(f"          ошибка: {job.last_error[:100]}")
        target = self.folder / "status.txt"
        partial = target.with_suffix(".part")
        await asyncio.to_thread(partial.write_text, "\n".join(lines) + "\n", "utf-8")
        await asyncio.to_thread(partial.replace, target)

    async def _handle(self, request: dict[str, Any]) -> str:
        kind = request["kind"]
        if kind == "video":
            job = Job.new(str(request["story"]), self._recipe_for(request))
            await self._store.add(job)
            return f"queued {job.id}"
        if kind == "approve":
            job = await self._find(str(request["job"]))
            if job.status is not Status.ASSEMBLED:
                raise LookupError(f"job {job.id} is {job.status.value}, not assembled")
            job.status = Status.APPROVED
            await self._store.save(job)
            return f"approved {job.id}"
        if kind == "series":
            return await self._series(request)
        if kind == "pause":
            (self.folder / "paused").touch()
            return "paused"
        if kind == "resume":
            (self.folder / "paused").unlink(missing_ok=True)
            return "resumed"
        raise ValueError(f"unknown request kind {kind!r}")

    async def _series(self, request: dict[str, Any]) -> str:
        recipe = self._recipe_for(request)
        style = self._styles.get(recipe.style)
        await self._before_llm()
        serial = await self._make_serial(str(request["story"]), style, int(request["episodes"]))
        name = str(request.get("name") or "series")
        notes, queue = write_serial(serial, recipe.style, self.folder / "series", name)
        if not request.get("queue"):
            return f"wrote {notes.name} and {queue.name}"
        lines = queue.read_text(encoding="utf-8").splitlines()
        for _, _, idea in ideas(lines):
            await self._store.add(Job.new(idea, recipe))
        return f"wrote {notes.name}, queued {len(serial.outlines)} episodes"

    def _recipe_for(self, request: dict[str, Any]) -> Recipe:
        update: dict[str, Any] = {"style": request.get("style") or self._recipe.style}
        update |= ANIMATION.get(str(request.get("animation", "hybrid")), {})
        if request.get("same_faces"):
            update["cast_image"] = "qwen-edit"
        self._styles.get(update["style"])
        return self._recipe.model_copy(update=update)

    async def _find(self, prefix: str) -> Job:
        wanted = prefix.strip().lower()
        found = [j for j in await self._store.find() if str(j.id).startswith(wanted)]
        if len(found) != 1:
            raise LookupError(f"{len(found)} jobs start with {wanted!r}")
        return found[0]
