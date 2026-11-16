"""The stages in the order a job goes through them."""

from reelsmith import scenes, story
from reelsmith.jobs import Stage, Status


def stages() -> list[Stage]:
    return [
        Stage("write", Status.NEW, Status.WRITTEN, story.write),
        Stage("stage", Status.VOICED, Status.STAGED, scenes.stage),
    ]
