"""Story parts lifted from gripping public-domain books, cut into roles and recombined
into short ideas: a world in catastrophe, a hero against it, a goal, two obstacles each
with the trick that beats it, an ally with a secret, a reversal and a closing hook.

The planner turns such an idea into a beat-by-beat outline, so an idea only has to carry
the parts; their order and the causes between them are the planner's job."""

import random
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Kind = Literal["world", "hero", "goal", "obstacle", "ally", "twist", "ending"]
KINDS: tuple[Kind, ...] = ("world", "hero", "goal", "obstacle", "ally", "twist", "ending")


class Source(BaseModel):
    id: str
    title: str = Field(description="Author, title, year; the work is in the public domain.")
    why: str = Field(description="What in its structure holds a reader.")


class Part(BaseModel):
    """A world's `themes` are a broad theme and the world's own tag; other parts list the
    tags they make sense with, or "any"."""

    kind: Kind
    text: str
    source: str
    themes: list[str] = Field(default_factory=lambda: ["any"])

    def fits(self, tags: list[str]) -> bool:
        return "any" in self.themes or bool(set(self.themes) & set(tags))


class Library(BaseModel):
    sources: list[Source]
    parts: list[Part]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        known = {s.id for s in self.sources}
        for part in self.parts:
            if part.source not in known:
                raise ValueError(f"part {part.text[:40]!r} cites unknown source {part.source!r}")
        for world in self.worlds():
            for kind in KINDS[1:]:
                enough = 2 if kind == "obstacle" else 1
                if len(self.fitting(kind, world.themes)) < enough:
                    raise ValueError(f"world {world.text[:40]!r} has no {kind} that fits it")
        return self

    def worlds(self) -> list[Part]:
        return [p for p in self.parts if p.kind == "world"]

    def themes(self) -> list[str]:
        return sorted({t for w in self.worlds() for t in w.themes})

    def fitting(self, kind: Kind, tags: list[str]) -> list[Part]:
        return [p for p in self.parts if p.kind == kind and p.fits(tags)]

    def title_of(self, source: str) -> str:
        return next(s.title for s in self.sources if s.id == source)


def load(path: Path) -> Library:
    return Library.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Remix:
    theme: str
    world: Part
    hero: Part
    goal: Part
    obstacles: tuple[Part, Part]
    ally: Part
    twist: Part
    ending: Part

    def idea(self) -> str:
        first, second = self.obstacles
        return (
            f"{self.world.text} {self.hero.text} Цель: {self.goal.text} "
            f"Первое препятствие: {first.text} Второе: {second.text} {self.ally.text} "
            f"Поворот: {self.twist.text} Финал: {self.ending.text}"
        )

    def parts(self) -> list[Part]:
        return [
            self.world,
            self.hero,
            self.goal,
            *self.obstacles,
            self.ally,
            self.twist,
            self.ending,
        ]


def remix(
    library: Library, count: int, *, seed: int, themes: list[str] | None = None
) -> list[Remix]:
    """`count` ideas; worlds rotate before any repeats, and each idea draws the rest of its
    parts from those that fit the world's tags. The same seed gives the same ideas."""
    rng = random.Random(seed)
    worlds = [w for w in library.worlds() if not themes or set(w.themes) & set(themes)]
    if not worlds:
        raise ValueError(f"no world for themes {themes}; have: {', '.join(library.themes())}")
    rng.shuffle(worlds)
    made: list[Remix] = []
    for n in range(count):
        world = worlds[n % len(worlds)]

        def one(kind: Kind, tags: list[str] = world.themes) -> Part:
            return rng.choice(library.fitting(kind, tags))

        first, second = rng.sample(library.fitting("obstacle", world.themes), 2)
        made.append(
            Remix(world.themes[0], world, one("hero"), one("goal"), (first, second), one("ally"),
                  one("twist"), one("ending"))
        )  # fmt: skip
    return made


def ideas_file(made: list[Remix], library: Library, style: str, seed: int) -> str:
    lines = [f"# remix, seed {seed}. One line, one idea: ./run.sh ideas ..."]
    for n, item in enumerate(made, 1):
        sources = sorted({library.title_of(p.source) for p in item.parts()})
        lines += [
            "",
            f"# {n:02d} · {item.theme} · " + "; ".join(sources),
            f"[{style}] {item.idea()}",
        ]
    return "\n".join(lines) + "\n"
