from pathlib import Path

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
        hero="artem",
        want="Артём хочет подняться выше воды.",
        obstacle="Вода поднимается на этаж в час, а лестница одна.",
        places=ep.places,
        beats=[b.text[:40] for b in ep.beats],
        planted="рация",
        ending=ep.ending,
        narration=_narration(ep),
        stakes_line="Через шесть часов она будет под самой крышей.",
        turn_line="В темноте игрушечная рация Лены говорит взрослым женским голосом.",
    ).model_copy(update={"characters": [
        story.Person(key="artem", name="Артём", look="man, 30", who="жилец третьего этажа"),
        story.Person(key="lena", name="Лена", look="girl, 10", who="девочка десяти лет"),
    ]})  # fmt: skip


HEARD = {"hero": "Артём", "wants": "подняться выше воды", "danger": "утонуть",
         "story": "Артём поднимается по лестнице от воды.", "unclear": []}  # fmt: skip
PAW = (
    "Ночь. Ливень бьёт по стеклу гостиной, где мистер Уайт играет в шахматы с Гербертом. "
    "Вдруг стучатся: это Моррис, вернувшийся из Индии через двадцать лет службы. Он достаёт "
    "из кармана маленькую высохшую обезьянью лапу и кладёт её на стол. Мистер Уайт сжимает "
    "лапу и загадывает двести фунтов. Лапа извивается в его ладони, как живая змея. Все "
    "уходят спать. В углях ему мерещится обезьянья морда."
)


def _paw(**changes: object) -> Outline:
    people = [
        story.Person(key="white", name="мистер Уайт", look="man, 60", who="старик, хозяин дома"),
        story.Person(key="herbert", name="Герберт", look="man, 25", who="его сын"),
        story.Person(key="morris", name="Моррис", look="man, 55", who="старый друг семьи"),
    ]
    base = _outline(_golden()).model_copy(update={
        "characters": people, "hero": "white", "narration": PAW,
        "ending": "В углях ему мерещится обезьянья морда.",
        "stakes_line": "Мистер Уайт сжимает лапу и загадывает двести фунтов.",
        "turn_line": "Лапа извивается в его ладони, как живая змея.",
    })  # fmt: skip
    return base.model_copy(update=changes)


def test_the_golden_narration_can_be_followed() -> None:
    assert story.unclear(_outline(_golden())) == []


def test_people_named_without_a_word_on_who_they_are_are_listed() -> None:
    found = story.unclear(_paw())
    said = next(p for p in found if "who they are" in p)
    assert all(name in said for name in ("Герберт", "Моррис", "мистер Уайт"))


def test_a_person_introduced_in_the_next_sentence_is_known() -> None:
    told = PAW.replace("с Гербертом.", "с Гербертом. Это его сын.")
    said = next(p for p in story.unclear(_paw(narration=told)) if "who they are" in p)
    assert "Герберт (" not in said


def test_stakes_said_late_and_a_turn_said_early_are_reported() -> None:
    found = story.unclear(_paw(
        stakes_line="Все уходят спать.",
        turn_line="Вдруг стучатся: это Моррис, вернувшийся из Индии через двадцать лет службы.",
    ))  # fmt: skip
    assert any("too late" in p for p in found)
    assert any("first half" in p for p in found)


def test_a_line_that_is_not_in_the_narration_and_a_hero_who_comes_late_are_reported() -> None:
    found = story.unclear(_paw(hero="morris", stakes_line="Этого в тексте нет."))
    assert any("`stakes_line` is a sentence" in p for p in found)
    found = story.unclear(_paw(narration="Ночь. Дождь. Темно. Тихо. " + PAW))
    assert any("whose story it is" in p for p in found)


def test_a_long_sentence_and_a_changed_ending_are_reported() -> None:
    long = "Он " + "идёт и " * 12 + "падает."
    found = story.unclear(_paw(narration=f"{PAW} {long}"))
    assert any("too long to follow" in p for p in found)
    assert any("`ending`" in p for p in found)


def test_what_the_listener_missed_goes_back_to_the_planner() -> None:
    heard = story.Heard(hero="Моррис", wants="not said", danger="смерть", story="…",
                        unclear=["«лапу» — what the paw does is never said"])  # fmt: skip
    found = story.misheard(_paw(), heard)
    assert any("took «Моррис» for the hero" in p for p in found)
    assert any("wants or fears" in p for p in found)
    assert any("what the paw does" in p for p in found)
    assert story.misheard(_paw(), story.Heard(**{**HEARD, "hero": "старик Уайт"})) == []


async def test_a_plan_the_listener_could_not_follow_is_written_again(tmp_path: Path) -> None:
    outline = _outline(_golden())
    lost = {**HEARD, "unclear": ["«рация» — whose radio it is"]}
    llm = FakeLlm().answer("Outline", outline, outline).answer("Heard", lost, HEARD)
    made, heard, left = await story.plan(context(tmp_path, llm), STYLE, "идея")
    assert made == outline
    assert left == []
    assert heard is not None
    assert "whose radio it is" in llm.calls[2][3]
    assert llm.calls[1][3] == outline.narration


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
    llm = FakeLlm().answer("Outline", long, short).answer("Heard", HEARD)
    outline, _, left = await story.plan(context(tmp_path, llm), STYLE, "идея")
    assert outline == short
    assert left == []
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
        .answer("Heard", HEARD)
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
    page = (jobs.folder(job) / "script.md").read_text(encoding="utf-8")
    assert "Что понял слушатель" in page
    assert "Герой: Артём" in page


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


def test_a_card_shows_what_the_look_names_and_nothing_it_does_not() -> None:
    card = story.PLAIN_CARD.model_copy(update={"extras": ["scarf", "bag"], "face": ["beard"]})
    white = story.faithful(card, "man, 60, thin grey hair, round spectacles, brown cardigan")
    assert (white.face, white.extras, white.hat) == (["glasses"], [], "none")
    morris = story.faithful(card, "man, 55, bald, thick grey moustache, red army coat, a cap")
    assert (morris.face, morris.hair, morris.hat) == (["mustache"], "bald", "cap")
    lady = story.faithful(story.PLAIN_CARD, "woman, 58, freckles, white shawl, a string of pearls")
    assert (lady.face, lady.extras) == (["freckles"], ["necklace", "scarf"])
