"""One client for every model, through the OpenAI-compatible chat API that ollama and vLLM
both serve. Answers that must have a shape come back as JSON checked against a pydantic
model; code comes back as the last fenced block of a plain answer."""

import base64
import json
import re
from collections.abc import Sequence
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"```(?:js|javascript|mjs)?[ \t]*\n(.*?)(?:```|\Z)", re.DOTALL)
_SCENE = re.compile(r"function\s+scene\s*\(.*", re.DOTALL)
CODE_TOKENS = 4000  # a scene is some forty lines; room is left for a model that thinks first


class LlmError(Exception):
    pass


class NoCode(LlmError):
    """The model answered, with no code in the answer."""


class Llm:
    def __init__(
        self,
        url: str,
        *,
        temperature: float = 0.7,
        timeout: float = 900,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/") + "/chat/completions"
        self._temperature = temperature
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def json[T: BaseModel](
        self,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        images: Sequence[Path] = (),
    ) -> T:
        """The answer as `schema`. An answer that does not fit goes back once with the reason."""
        messages = [_message("system", system), _message("user", user, images)]
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        answer = await self._chat(model, messages, response_format)
        try:
            return schema.model_validate_json(answer)
        except ValidationError as exc:
            messages += [
                {"role": "assistant", "content": answer},
                _message("user", f"That answer does not fit the schema: {exc}. Answer again."),
            ]
        answer = await self._chat(model, messages, response_format)
        try:
            return schema.model_validate_json(answer)
        except ValidationError as exc:
            raise LlmError(f"{model} gave no valid {schema.__name__}: {exc}") from exc

    async def text(self, model: str, system: str, user: str) -> str:
        return await self._chat(model, [_message("system", system), _message("user", user)])

    async def code(
        self, model: str, system: str, user: str, *, temperature: float | None = None
    ) -> str:
        """The last fenced code block of the answer; a block the answer never closed counts,
        and so does bare code that defines the scene. The answer is cut at CODE_TOKENS."""
        answer = await self._chat(
            model,
            [_message("system", system), _message("user", user)],
            temperature=temperature,
            max_tokens=CODE_TOKENS,
        )
        blocks = [b for b in _FENCE.findall(answer) if b.strip()]
        if blocks:
            return str(blocks[-1]).strip()
        if bare := _SCENE.search(answer):
            return bare.group(0).strip()
        raise NoCode(f"{model} answered without code")

    async def _chat(
        self,
        model: str,
        messages: list[dict[str, object]],
        response_format: object = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        body: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise LlmError(f"{model} is unreachable at {self._url}: {exc}") from exc
        if response.status_code != httpx.codes.OK:
            raise LlmError(f"{model} answered {response.status_code}: {response.text[:300]}")
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LlmError(f"{model} answered in an unknown shape: {response.text[:300]}") from exc


def _message(role: str, text: str, images: Sequence[Path] = ()) -> dict[str, object]:
    if not images:
        return {"role": role, "content": text}
    parts: list[dict[str, object]] = [{"type": "text", "text": text}]
    for image in images:
        data = base64.b64encode(image.read_bytes()).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}})
    return {"role": role, "content": parts}
