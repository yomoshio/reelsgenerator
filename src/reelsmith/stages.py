"""The stages in the order a job goes through them."""

from reelsmith import story
from reelsmith.jobs import Stage, Status


def stages() -> list[Stage]:
    return [Stage("write", Status.NEW, Status.WRITTEN, story.write)]
