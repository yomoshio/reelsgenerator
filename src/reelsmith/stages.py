"""The stages in the order a job goes through them."""

from reelsmith import assemble, render, scenes, story, voice
from reelsmith.jobs import Stage, Status


def stages() -> list[Stage]:
    return [
        Stage("write", Status.NEW, Status.WRITTEN, story.write),
        Stage("voice", Status.WRITTEN, Status.VOICED, voice.voice),
        Stage("stage", Status.VOICED, Status.STAGED, scenes.stage),
        Stage("render", Status.STAGED, Status.RENDERED, render.render),
        Stage("assemble", Status.RENDERED, Status.ASSEMBLED, assemble.assemble),
    ]
