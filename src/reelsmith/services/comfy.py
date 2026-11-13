"""ComfyUI over HTTP: the key frames, the clips and the music.

Graphs are kept in API format in workflows/. Inputs the code fills in are marked by node
title: a node titled `@prompt:text` gets its `text` input replaced by the `prompt` value.
A title may carry several slots (`@width:width @height:height`), and one slot may mark
several nodes, which Wan 2.2 needs: its two samplers share a seed and a step count."""

from __future__ import annotations

import asyncio
import copy
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from reelsmith.models import StageError

Graph = dict[str, dict[str, Any]]

WAN_FPS = 16


class WorkflowMismatch(Exception):
    """The exported graph and the code disagree about its slots. Fix the JSON."""


@dataclass(frozen=True, slots=True)
class Slot:
    node: str
    field: str


class Workflow:
    def __init__(self, name: str, graph: Graph) -> None:
        self.name = name
        self._graph = graph
        self._slots = _find_slots(graph)

    @classmethod
    def load(cls, path: Path) -> Workflow:
        return cls(path.stem, json.loads(path.read_text(encoding="utf-8")))

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(self._slots)

    def require(self, *names: str) -> Workflow:
        """Called at startup so a badly exported graph stops the worker, not job #40."""
        missing = set(names) - self.slots
        if missing:
            raise WorkflowMismatch(f"{self.name}: no nodes titled for {sorted(missing)}")
        return self

    def supported(self, **values: object) -> dict[str, object]:
        """The values this graph has slots for; a hand-made graph may lack the optional ones."""
        return {name: value for name, value in values.items() if name in self._slots}

    def bind(self, **values: object) -> Graph:
        unknown = values.keys() - self._slots.keys()
        if unknown:
            raise WorkflowMismatch(f"{self.name}: no slots named {sorted(unknown)}")
        graph = copy.deepcopy(self._graph)
        for name, value in values.items():
            for slot in self._slots[name]:
                graph[slot.node]["inputs"][slot.field] = value
        return graph


def _find_slots(graph: Graph) -> dict[str, list[Slot]]:
    slots: dict[str, list[Slot]] = defaultdict(list)
    for node_id, node in graph.items():
        title = node.get("_meta", {}).get("title", "")
        if not title.startswith("@"):
            continue
        for token in title.split():
            name, sep, field = token.removeprefix("@").partition(":")
            if not token.startswith("@") or not sep or field not in node.get("inputs", {}):
                raise WorkflowMismatch(
                    f"node {node_id} title {title!r}: each part must be @slot:<existing input>"
                )
            slots[name].append(Slot(node_id, field))
    return dict(slots)


@dataclass(frozen=True, slots=True)
class Output:
    filename: str
    subfolder: str
    kind: str


class ComfyClient:
    def __init__(self, http: httpx.AsyncClient, *, poll_seconds: float = 2.0) -> None:
        self._http = http
        self._poll = poll_seconds
        self._client_id = uuid4().hex

    async def run(self, graph: Graph, *, limit: float) -> list[Output]:
        body = {"prompt": graph, "client_id": self._client_id}
        queued = (await self._call("POST", "/prompt", json=body)).json()
        if queued.get("node_errors"):
            raise StageError(f"comfy: graph rejected: {queued['node_errors']}")
        prompt_id = queued["prompt_id"]
        try:
            async with asyncio.timeout(limit):
                return await self._wait(prompt_id)
        except TimeoutError:
            await self._call("POST", "/interrupt")
            raise StageError(f"comfy: prompt {prompt_id} did not finish in {limit:.0f}s") from None

    async def upload(self, image: Path) -> str:
        content = await asyncio.to_thread(image.read_bytes)
        reply = await self._call(
            "POST",
            "/upload/image",
            files={"image": (image.name, content, "image/png")},
            data={"overwrite": "true"},
        )
        uploaded = reply.json()
        subfolder = uploaded.get("subfolder")
        return f"{subfolder}/{uploaded['name']}" if subfolder else str(uploaded["name"])

    async def download(self, output: Output, dest: Path) -> Path:
        params = {"filename": output.filename, "subfolder": output.subfolder, "type": output.kind}
        reply = await self._call("GET", "/view", params=params)
        await asyncio.to_thread(dest.write_bytes, reply.content)
        return dest

    async def release(self) -> None:
        await self._call("POST", "/free", json={"unload_models": True, "free_memory": True})

    async def _wait(self, prompt_id: str) -> list[Output]:
        while True:
            history = (await self._call("GET", f"/history/{prompt_id}")).json()
            entry = history.get(prompt_id)
            if entry is None:
                await asyncio.sleep(self._poll)
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise StageError(f"comfy: prompt {prompt_id} failed: {_error_text(status)}")
            return _outputs(entry.get("outputs", {}))

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # While a prompt renders, ComfyUI can take far longer than httpx's default five
        # seconds to answer even a small request; a timeout there cost a whole attempt.
        kwargs.setdefault("timeout", 120)
        try:
            reply = await self._http.request(method, path, **kwargs)
            reply.raise_for_status()
        except httpx.HTTPError as exc:
            raise StageError(f"comfy: {method} {path}: {type(exc).__name__} {exc}".strip()) from exc
        return reply


def _outputs(node_outputs: dict[str, dict[str, Any]]) -> list[Output]:
    # Images arrive under "images", VideoHelperSuite videos under "gifs", audio under "audio".
    found: list[Output] = []
    for produced in node_outputs.values():
        for files in produced.values():
            if not isinstance(files, list):
                continue
            found += [
                Output(f["filename"], f.get("subfolder", ""), f.get("type", "output"))
                for f in files
                if isinstance(f, dict) and "filename" in f
            ]
    return found


def _error_text(status: dict[str, Any]) -> str:
    for kind, detail in status.get("messages", []):
        if kind == "execution_error":
            return f"{detail.get('node_type')}: {detail.get('exception_message', '').strip()}"
    return "unknown error"


def _first(outputs: list[Output], suffixes: tuple[str, ...], workflow: str) -> Output:
    for output in outputs:
        if output.filename.lower().endswith(suffixes):
            return output
    raise StageError(f"comfy: {workflow} produced no {'/'.join(suffixes)} file")


def wan_length(seconds: float, fps: int = WAN_FPS) -> int:
    """Wan wants 4k+1 frames; round the shot up so it is never shorter than its voice line."""
    frames = int(seconds * fps + 0.999)
    return frames + (-(frames - 1) % 4)


class ComfyPainter:
    def __init__(
        self,
        client: ComfyClient,
        workflow: Workflow,
        *,
        name: str = "z-image",
        width: int = 720,
        height: int = 1280,
        steps: int = 8,
        placed: Workflow | None = None,
    ) -> None:
        self.name = name
        self._client = client
        self._workflow = workflow.require("prompt", "seed")
        self._placed = placed.require("prompt", "seed", "image", "place") if placed else None
        self._knobs = workflow.supported(width=width, height=height, steps=steps)

    async def paint(
        self,
        prompt: str,
        *,
        seed: int,
        out: Path,
        reference: Path | None = None,
        place: Path | None = None,
    ) -> Path:
        """A graph with an `image` slot draws from `reference`; others ignore it. With a
        `place` as well, the `placed` graph draws from both, when there is one."""
        workflow, extra = self._workflow, {}
        if reference is not None and "image" in workflow.slots:
            extra["image"] = await self._client.upload(reference)
            if place is not None and self._placed is not None:
                workflow = self._placed
                extra["place"] = await self._client.upload(place)
        graph = workflow.bind(prompt=prompt, seed=seed, **self._knobs, **extra)
        outputs = await self._client.run(graph, limit=180)
        return await self._client.download(_first(outputs, (".png",), workflow.name), out)


class ComfyAnimator:
    """Any Wan 2.2 graph: the 14B model at 16 fps or the 5B draft at 24 fps."""

    def __init__(
        self,
        client: ComfyClient,
        workflow: Workflow,
        *,
        name: str = "wan-2.2",
        fps: int = WAN_FPS,
        max_seconds: float = 5.0,
        width: int = 480,
        height: int = 848,
        steps: int = 4,
    ) -> None:
        self.name = name
        self.max_seconds = max_seconds
        self._fps = fps
        self._client = client
        self._workflow = workflow.require("image", "prompt", "length", "seed")
        # The high-noise expert takes the first half of the steps, the low-noise one the rest.
        self._knobs = workflow.supported(
            width=width, height=height, steps=steps, split=max(steps // 2, 1)
        )

    def length(self, seconds: float) -> float:
        return wan_length(seconds, self._fps) / self._fps

    async def animate(
        self, frame: Path, motion: str, *, seconds: float, seed: int, out: Path
    ) -> Path:
        image = await self._client.upload(frame)
        length = wan_length(seconds, self._fps)
        graph = self._workflow.bind(
            image=image, prompt=motion, length=length, seed=seed, **self._knobs
        )
        outputs = await self._client.run(graph, limit=1800)
        return await self._client.download(_first(outputs, (".mp4",), self._workflow.name), out)


class ComfyComposer:
    suffix = ".flac"

    def __init__(
        self, client: ComfyClient, workflow: Workflow, *, name: str = "ace-step", steps: int = 8
    ) -> None:
        self.name = name
        self._client = client
        self._workflow = workflow.require("tags", "seconds", "seed")
        self._knobs = workflow.supported(steps=steps)

    async def compose(self, brief: str, *, seconds: float, seed: int, out: Path) -> Path:
        graph = self._workflow.bind(tags=brief, seconds=round(seconds, 1), seed=seed, **self._knobs)
        outputs = await self._client.run(graph, limit=300)
        suffixes = (".flac", ".mp3", ".wav")
        return await self._client.download(_first(outputs, suffixes, self._workflow.name), out)
