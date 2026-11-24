from pathlib import Path

import pytest

from reelsmith import story
from reelsmith.catalog import Catalog
from reelsmith.jobs import Jobs, Source
from reelsmith.story import Episode, Outline, Reveal, Staging, problems
from reelsmith.styles import Styles
from tests.fakes import DATA, REPO, FakeLlm, context

STYLE = Styles(REPO / "styles").get("blackout")


def _golden() -> Episode:
    return Episode.model_validate_json((DATA / "flood-01.json").read_text(encoding="utf-8"))


def _narration(ep: Episode) -> str:
    return " ".join(b.text for b in ep.beats)


def _staged(ep: Episode) -> Episode:
    things = {"room": ["bed", "door", "window", "water"], "stairwell": ["railing", "wardrobe"]}
    beats = []
    for beat in ep.beats:
        kind = ep.place(beat.place).kind
        here = [*things.get(kind, []), "door", "table", "window"]
        stage = Staging(
            shot="wide", action="Artem stands.", things=here, questions=["Is he there?"]
        )
        beats.append(beat.model_copy(update={"staging": stage}))
    return ep.model_copy(update={"beats": beats})


def _outline(ep: Episode) -> Outline:
    return Outline(
        title=ep.title,
        premise=ep.premise,
        characters=[
            story.Person(**c.model_dump(include={"key", "name", "look"})) for c in ep.characters
        ],
        places=ep.places,
        beats=[b.text[:40] for b in ep.beats],
        planted="рация",
        ending=ep.ending,
        narration=_narration(ep),
    )


def test_the_golden_episode_passes_every_check() -> None:
    ep = _golden()
    assert problems(ep, STYLE, "ru", _narration(ep)) == []


def test_a_reworded_line_is_named() -> None:
    ep = _golden()
    narration = _narration(ep)
    beats = list(ep.beats)
    for n in (3, 4, 5):
        beats[n] = beats[n].model_copy(update={"lines": ["Совсем другие слова здесь звучат."]})
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", narration)
    assert any("word for word" in p and "became" in p for p in found)


def test_a_plate_on_a_word_never_said_is_reported() -> None:
    ep = _golden()
    beat = ep.beats[2]
    wrong = Reveal(on_word="самолёт", kind="label", text="самолёт", target="artem")
    beats = [
        *ep.beats[:2],
        beat.model_copy(update={"reveals": [*beat.reveals, wrong]}),
        *ep.beats[3:],
    ]
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", _narration(ep))
    assert any("beat 3 'самолёт'" in p for p in found)


def test_unknown_places_and_people_are_reported() -> None:
    ep = _golden()
    beats = [
        ep.beats[0].model_copy(update={"place": "moon", "cast": ["artem", "boris"]}),
        *ep.beats[1:],
    ]
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", _narration(ep))
    assert any("'moon'" in p and "boris" in p for p in found)


def test_the_hook_needs_a_threat_plate_early() -> None:
    ep = _golden()
    first = ep.beats[0]
    calm = [r.model_copy(update={"tone": "neutral"}) for r in first.reveals]
    beats = [first.model_copy(update={"reveals": calm}), *ep.beats[1:]]
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", _narration(ep))
    assert any("tone 'threat'" in p for p in found)


def test_staging_keeps_things_in_their_place_and_plates_on_stage() -> None:
    ep = _staged(_golden())
    assert problems(ep, STYLE, "ru", _narration(ep), Catalog()) == []
    later = [i for i, b in enumerate(ep.beats) if b.place == "stairwell"][1]
    beat = ep.beats[later]
    assert beat.staging is not None
    shrunk = beat.staging.model_copy(update={"things": ["railing", "door", "table", "window"]})
    beats = list(ep.beats)
    beats[later] = beat.model_copy(update={"staging": shrunk})
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", _narration(ep), Catalog())
    assert any("lost wardrobe" in p for p in found)


def test_a_plate_pinned_to_a_thing_off_stage_is_reported() -> None:
    ep = _staged(_golden())
    people = {c.key for c in ep.characters}
    n = next(
        i
        for i, b in enumerate(ep.beats)
        if any(r.target and r.target not in people for r in b.reveals)
    )
    beat = ep.beats[n]
    assert beat.staging is not None
    bare = beat.staging.model_copy(update={"things": []})
    beats = list(ep.beats)
    beats[n] = beat.model_copy(update={"staging": bare})
    found = problems(ep.model_copy(update={"beats": beats}), STYLE, "ru", _narration(ep), Catalog())
    assert any("not on stage" in p for p in found)


async def test_the_plan_is_made_again_while_the_narration_is_too_long(tmp_path: Path) -> None:
    ep = _golden()
    short = _outline(ep)
    long = short.model_copy(update={"narration": short.narration * 3})
    llm = FakeLlm().answer("Outline", long, short)
    outline = await story.plan(context(tmp_path, llm), STYLE, "идея")
    assert outline == short
    assert "was off" in llm.calls[1][3]


async def test_the_editor_is_skipped_unless_set(tmp_path: Path) -> None:
    outline = _outline(_golden())
    llm = FakeLlm()
    assert await story.edit(context(tmp_path, llm), outline) == outline
    assert llm.calls == []


async def test_an_edit_that_changes_the_length_is_not_kept(tmp_path: Path) -> None:
    outline = _outline(_golden())
    llm = FakeLlm().answer("Edited", {"narration": "Коротко.", "ending": outline.ending})
    assert await story.edit(context(tmp_path, llm, editor="t-pro"), outline) == outline


async def test_the_cut_is_sent_back_with_its_problems(tmp_path: Path) -> None:
    ep = _golden()
    good = {"hook": ep.hook, "hud": ep.hud, "beats": [b.model_dump() for b in ep.beats],
            "cliffhanger": ep.cliffhanger, "music": "drone"}  # fmt: skip
    bad = {**good, "hook": "Совсем не то начало"}
    llm = FakeLlm().answer("Cut", bad, good)
    made, left = await story.cut(context(tmp_path, llm), STYLE, _outline(ep))
    assert left == []
    assert made.hook == ep.hook
    assert "Fix these problems" in llm.calls[1][3]


async def test_the_write_stage_leaves_a_staged_cast_episode(tmp_path: Path) -> None:
    ep = _golden()
    staged = _staged(ep)
    card = {"age": "adult", "build": "average", "skin": "light", "hair": "short",
            "hair_colour": "#222222", "top": "raincoat", "top_colour": "#2E4A70",
            "bottom": "trousers", "bottom_colour": "#1C2230", "shoes_colour": "#101014"}  # fmt: skip
    llm = (
        FakeLlm()
        .answer("Outline", _outline(ep))
        .answer(
            "Cut",
            {
                "hook": ep.hook,
                "hud": ep.hud,
                "beats": [b.model_dump() for b in ep.beats],
                "cliffhanger": ep.cliffhanger,
                "music": "drone",
            },
        )
        .answer("Cast", {"cards": [{"key": "artem", "card": card}, {"key": "lena", "card": card}]})
        .answer("Direction", {"beats": [b.staging.model_dump() for b in staged.beats if b.staging]})
    )
    ctx = context(tmp_path, llm)
    jobs = Jobs(ctx.settings.jobs)
    job = jobs.create(Source(kind="idea", text="Вода по колено"), "blackout")
    await story.write(job, jobs.folder(job), ctx)
    made = Episode.model_validate_json((jobs.folder(job) / "episode.json").read_text())
    assert all(c.card is not None for c in made.characters)
    assert all(b.staging is not None for b in made.beats)
    assert (jobs.folder(job) / "plan.json").is_file()


async def test_cards_under_other_keys_are_taken_in_order_and_a_missing_one_is_plain(
    tmp_path: Path,
) -> None:
    ep = _golden()
    card = story.PLAIN_CARD.model_copy(update={"top_colour": "#AA0000"}).model_dump()
    renamed = {"cards": [{"key": f"mister_{c.key}", "card": card} for c in ep.characters]}
    made = await story.cast(context(tmp_path, FakeLlm().answer("Cast", renamed)), STYLE, ep)
    assert all(c.card and c.card.top_colour == "#AA0000" for c in made.characters)

    llm = FakeLlm().answer("Cast", {"cards": []}, {"cards": []})
    plain = await story.cast(context(tmp_path, llm), STYLE, ep)
    assert all(c.card == story.PLAIN_CARD for c in plain.characters)
    assert len(llm.calls) == 2


async def test_a_director_who_stages_nothing_is_asked_again(tmp_path: Path) -> None:
    staged = _staged(_golden())
    ep = _golden()
    good = {"beats": [b.staging.model_dump() for b in staged.beats if b.staging]}
    llm = FakeLlm().answer("Direction", {"beats": []}, good)
    made, left = await story.direct(context(tmp_path, llm), STYLE, ep, _narration(ep), Catalog())
    assert left == []
    assert all(b.staging is not None for b in made.beats)
    assert "has no staging" in llm.calls[1][3]
