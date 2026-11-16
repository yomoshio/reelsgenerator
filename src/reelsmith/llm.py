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

_FENCE = re.compile(r"```(?:js|javascript|mjs)?[ \t]*\n(.*?)```", re.DOTALL)


class LlmError(Exception):
    pass


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

    async def code(self, model: str, system: str, user: str) -> str:
        """The last fenced code block of the answer."""
        answer = await self.text(model, system, user)
        blocks = _FENCE.findall(answer)
        if not blocks:
            raise LlmError(f"{model} answered without a fenced code block")
        return str(blocks[-1]).strip()

    async def _chat(
        self, model: str, messages: list[dict[str, object]], response_format: object = None
    ) -> str:
        body: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": self._temperature,
        }
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
