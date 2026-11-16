from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

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

    async def code(self, model: str, system: str, user: str) -> str:
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
