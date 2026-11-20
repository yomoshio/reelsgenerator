import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from reelsmith.llm import CODE_TOKENS, Llm, LlmError, NoCode


class Answer(BaseModel):
    title: str
    count: int


def _replies(*contents: str) -> tuple[httpx.MockTransport, list[dict[str, object]]]:
    sent: list[dict[str, object]] = []
    queue = list(contents)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": queue.pop(0)}}]})

    return httpx.MockTransport(handle), sent


async def test_json_validates_against_the_schema() -> None:
    transport, sent = _replies('{"title": "Утро", "count": 3}')
    llm = Llm("http://box/v1", transport=transport)
    answer = await llm.json("m", "sys", "user", Answer)
    assert answer == Answer(title="Утро", count=3)
    assert sent[0]["response_format"]["json_schema"]["name"] == "Answer"  # type: ignore[index]


async def test_json_retries_once_with_the_error() -> None:
    transport, sent = _replies('{"title": "x"}', '{"title": "x", "count": 1}')
    llm = Llm("http://box/v1", transport=transport)
    assert (await llm.json("m", "sys", "user", Answer)).count == 1
    last = sent[1]["messages"][-1]  # type: ignore[index]
    assert "does not fit the schema" in last["content"]


async def test_json_gives_up_after_the_retry() -> None:
    transport, _ = _replies("{}", "{}")
    with pytest.raises(LlmError, match="no valid Answer"):
        await Llm("http://box/v1", transport=transport).json("m", "s", "u", Answer)


async def test_code_takes_the_last_fenced_block() -> None:
    transport, _ = _replies(
        "first\n```js\nbad()\n```\nthen\n```javascript\nfunction scene(s) {}\n```"
    )
    code = await Llm("http://box/v1", transport=transport).code("m", "s", "u")
    assert code == "function scene(s) {}"


async def test_images_go_as_data_urls(tmp_path: Path) -> None:
    png = tmp_path / "k.png"
    png.write_bytes(b"\x89PNG")
    transport, sent = _replies('{"title": "a", "count": 0}')
    await Llm("http://box/v1", transport=transport).json("m", "s", "u", Answer, images=[png])
    parts = sent[0]["messages"][1]["content"]  # type: ignore[index]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_unreachable_box_is_an_llm_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    llm = Llm("http://box/v1", transport=httpx.MockTransport(refuse))
    with pytest.raises(LlmError, match="unreachable"):
        await llm.text("m", "s", "u")


async def test_code_survives_an_unclosed_block_and_bare_code() -> None:
    seen: list[dict[str, object]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        answers = [
            "Here:\n```js\nfunction scene(s) { s.place('room'); }",
            "function scene(s) {}",
            "No.",
        ]
        content = answers[len(seen) - 1]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    llm = Llm("http://x/v1", transport=httpx.MockTransport(reply))
    assert (await llm.code("m", "s", "u")).startswith("function scene(s) { s.place")
    assert await llm.code("m", "s", "u", temperature=0.1) == "function scene(s) {}"
    with pytest.raises(NoCode):
        await llm.code("m", "s", "u")
    assert seen[0]["max_tokens"] == CODE_TOKENS
    assert seen[1]["temperature"] == 0.1


async def test_a_code_answer_cut_at_the_limit_is_not_run() -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        choice = {"message": {"content": "```js\nfunction scene(s) {"}, "finish_reason": "length"}
        return httpx.Response(200, json={"choices": [choice]})

    llm = Llm("http://x/v1", transport=httpx.MockTransport(reply))
    with pytest.raises(NoCode, match="cut off"):
        await llm.code("m", "s", "u")


async def test_reasoning_is_off_unless_asked_for() -> None:
    transport, sent = _replies("a", "b")
    await Llm("http://box/v1", transport=transport).text("m", "s", "u")
    await Llm("http://box/v1", transport=transport, reasoning="").text("m", "s", "u")
    assert sent[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in sent[1]
