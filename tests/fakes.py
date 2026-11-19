import io
import wave
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from reelsmith.captions import Word
from reelsmith.jobs import Context
from reelsmith.settings import Settings
from reelsmith.styles import Styles

REPO = Path(__file__).parent.parent
DATA = Path(__file__).parent / "data"


class FakeLlm:
    """Answers from queues kept per schema name, `text` and `code`; records every call."""

    def __init__(self) -> None:
        self.queues: dict[str, list[Any]] = defaultdict(list)
        self.calls: list[tuple[str, str, str, str]] = []

    def answer(self, name: str, *replies: Any) -> "FakeLlm":
        self.queues[name] += replies
        return self

    async def json[T: BaseModel](
        self, model: str, system: str, user: str, schema: type[T], images: Sequence[Path] = ()
    ) -> T:
        self.calls.append((schema.__name__, model, system, user))
        reply = self.queues[schema.__name__].pop(0)
        return reply if isinstance(reply, schema) else schema.model_validate(reply)

    async def text(self, model: str, system: str, user: str) -> str:
        self.calls.append(("text", model, system, user))
        return str(self.queues["text"].pop(0))

    async def code(
        self, model: str, system: str, user: str, *, temperature: float | None = None
    ) -> str:
        self.calls.append(("code", model, system, user))
        return str(self.queues["code"].pop(0))

    async def close(self) -> None:
        return None


def context(tmp_path: Path, llm: FakeLlm, **settings: Any) -> Context:
    return Context(
        Settings(jobs=tmp_path / "jobs", styles=REPO / "styles", **settings),
        llm,  # type: ignore[arg-type]
        Styles(REPO / "styles"),
    )


def wav(seconds: float, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * round(seconds * rate))
    return buffer.getvalue()


class FakeSpeech:
    """Reads a text as silence of its length, and hears its words one after another; `extra`
    words are heard on the first take only, as if the narrator read a stage direction."""

    def __init__(self, extra: tuple[str, ...] = ()) -> None:
        self.extra = list(extra)
        self.spoken: list[str] = []
        self.unloaded = False

    async def speak(self, text: str, voice: str, language: str) -> bytes:
        self.spoken.append(text)
        return wav(0.4 * len(text.split()) + 0.3)

    async def words(self, audio: bytes, language: str, hint: str = "") -> list[Word]:
        said = [*self.extra, *hint.split()]
        self.extra = []
        return [Word(w, 0.2 + i * 0.4, 0.5 + i * 0.4) for i, w in enumerate(said)]

    async def unload(self) -> None:
        self.unloaded = True

    async def close(self) -> None:
        return None
