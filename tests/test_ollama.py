import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from reelsmith.models import Script, StageError, Verdict
from reelsmith.services.ollama import OllamaLlm
from tests.fakes import script

LOADED = [{"name": "qwen3.5:27b"}, {"name": "qwen3-vl:8b"}]


def _server(answers: list[object], seen: list[dict[str, Any]]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": LOADED})
        body = json.loads(request.content)
        seen.append({"path": request.url.path, **body})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={})
        content = json.dumps(answers.pop(0))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://llm")


def _llm(answers: list[object], seen: list[dict[str, Any]]) -> OllamaLlm:
    return OllamaLlm(
        _server(answers, seen), writer_model="qwen3.5:27b", judge_model="qwen3-vl:8b", language="ru"
    )


async def test_writer_sends_the_brief_and_parses_the_script() -> None:
    seen: list[dict[str, Any]] = []

    made = await _llm([script().model_dump(mode="json")], seen).write("зомби в метро")

    assert made == script()
    (call,) = seen
    assert (call["path"], call["model"], call["stream"]) == ("/api/chat", "qwen3.5:27b", False)
    assert call["format"] == Script.model_json_schema()
    assert call["messages"][0]["role"] == "system"
    assert "in ru" in call["messages"][0]["content"]
    assert call["messages"][1] == {"role": "user", "content": "зомби в метро"}


async def test_writer_passes_the_critics_notes_on_a_rewrite() -> None:
    seen: list[dict[str, Any]] = []

    await _llm([script().model_dump(mode="json")], seen).write("зомби в метро", "cut the last line")

    ask = seen[0]["messages"][1]["content"]
    assert ask.startswith("зомби в метро")
    assert "cut the last line" in ask


async def test_critic_uses_the_writer_model_at_low_temperature() -> None:
    seen: list[dict[str, Any]] = []

    verdict = await _llm([{"score": 6.5, "notes": "slow start"}], seen).review(script())

    assert verdict == Verdict(score=6.5, notes="slow start")
    assert seen[0]["model"] == "qwen3.5:27b"
    assert json.loads(seen[0]["messages"][1]["content"])["title"] == "t"
    assert seen[0]["options"]["temperature"] == 0.2


async def test_judge_sends_images_to_the_judge_model_and_clamps_the_pick(tmp_path: Path) -> None:
    frames = [tmp_path / f"{i}.png" for i in range(2)]
    for i, frame in enumerate(frames):
        frame.write_bytes(b"png%d" % i)
    seen: list[dict[str, Any]] = []

    assert await _llm([{"index": 5}], seen).pick("corridor", frames) == 1

    assert seen[0]["model"] == "qwen3-vl:8b"
    message = seen[0]["messages"][1]
    assert message["images"] == [base64.b64encode(f.read_bytes()).decode() for f in frames]
    assert "corridor" in message["content"]


async def test_judge_inspects_clips_and_reviews_the_cut(tmp_path: Path) -> None:
    stills = [tmp_path / "s.png"]
    stills[0].write_bytes(b"png")
    answers = [{"score": 4.0, "notes": "smear"}, {"score": 5.0, "notes": "drift", "bad_shots": [1]}]
    llm = _llm(answers, [])

    assert await llm.inspect("slow push in", stills) == Verdict(score=4.0, notes="smear")
    assert (await llm.judge(script(), stills)).bad_shots == [1]


async def test_bad_json_and_http_errors_become_stage_errors() -> None:
    with pytest.raises(StageError, match="Script does not match"):
        await _llm([{"title": "only"}], []).write("x")

    down = httpx.MockTransport(lambda request: httpx.Response(500))
    broken = OllamaLlm(
        httpx.AsyncClient(transport=down, base_url="http://llm"),
        writer_model="m", judge_model="m", language="ru",
    )  # fmt: skip
    with pytest.raises(StageError, match="ollama"):
        await broken.write("x")


async def test_release_unloads_every_loaded_model() -> None:
    seen: list[dict[str, Any]] = []

    await _llm([], seen).release()

    assert [(c["path"], c["model"], c["keep_alive"]) for c in seen] == [
        ("/api/generate", "qwen3.5:27b", 0),
        ("/api/generate", "qwen3-vl:8b", 0),
    ]
