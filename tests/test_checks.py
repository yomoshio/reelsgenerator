import pytest

from reelsmith.checks import misspoken, present, problems, spoken_seconds, unsaid_plates
from reelsmith.models import Character, Overlay, Script, Shot
from reelsmith.styles import Style
from tests.fakes import style


def flood(*shots: Shot) -> Script:
    return Script(
        title="Потоп",
        hook="water at the knees",
        hook_kind="threat",
        characters=[
            Character(name="Артём", look="man, 30, short dark hair, blue raincoat"),
            Character(name="Лена", look="girl, 10, yellow hooded jacket, red toy radio"),
        ],
        shots=list(shots),
        music="drone",
    )


def shot(line: str, *plates: Overlay, cast: tuple[str, ...] = ("Артём",), motion: str = "") -> Shot:
    return Shot(
        line=line,
        picture="p",
        motion=motion or "water ripples, slow push-in",
        cast=list(cast),
        stress=[line.split(maxsplit=1)[0]],
        overlays=list(plates),
    )


def plates(script: Script) -> list[tuple[int, str]]:
    return [(i, o.text) for i, o in unsaid_plates(script)]


def test_a_goal_plate_before_the_narrator_names_the_goal_is_early() -> None:
    goal = Overlay(kind="goal", text="ЦЕЛЬ: девятый этаж, мастерская")

    script = flood(
        shot("Артём просыпается: вода по колено.", goal),
        shot("Наверх, на девятый этаж, в мастерскую.", goal),
        shot("Лестница одна.", goal),
    )

    assert plates(script) == [(0, "ЦЕЛЬ: девятый этаж, мастерская")]


def test_a_number_on_a_plate_must_be_said_in_its_own_shot() -> None:
    script = flood(
        shot("Третий этаж из девяти.", Overlay(kind="count", text="ЭТАЖ 3 ИЗ 9")),
        shot("Шкаф перегородил лестницу.", Overlay(kind="count", text="ЭТАЖ 4 ИЗ 9")),
        shot("Пятый этаж.", Overlay(kind="count", text="ЭТАЖ 5 ИЗ 9")),
    )

    assert plates(script) == [(1, "ЭТАЖ 4 ИЗ 9")]


def test_a_plate_repeated_from_the_shot_before_carries_on() -> None:
    count = Overlay(kind="count", text="ЭТАЖ 32")

    script = flood(
        shot("Тридцать второй этаж.", count),
        shot("Свет гаснет.", count),
        shot("Тишина.", count),
    )

    assert plates(script) == []


def test_plates_match_words_in_any_case_form_and_skip_labels_and_numbering() -> None:
    script = flood(
        shot("Это Лена с красной рацией.", Overlay(kind="card", text="Лена | красная рация")),
        shot("Не открывай дверь.", Overlay(kind="rule", text="1. Не открывай дверь")),
        shot("Рация загорается сама.", Overlay(kind="alert", text="РАЦИЯ АКТИВНА")),
    )

    assert plates(script) == [(2, "РАЦИЯ АКТИВНА")]


def test_a_person_named_in_the_line_must_be_in_the_frame() -> None:
    script = flood(
        shot("Вода поднимается, Артём должен бежать наверх.", cast=()),
        shot("Фонарик Артёма гаснет.", cast=("Артём",)),
        shot("Лене страшно.", cast=("Артём",)),
    )

    assert [p for p in problems(script, style()) if "`cast`" in p] == [
        "Named in the line but missing from `cast`: shot 1 (Артём), shot 3 (Лена). "
        "Whoever the line names is in the picture and in `cast`."
    ]
    assert present(script.shots[2], script) == ["Артём", "Лена"]


def test_camera_moves_that_reveal_what_is_not_drawn_are_refused() -> None:
    script = flood(
        shot("Вода.", motion="Camera tilts up from the water to the dark upper floor."),
        shot("Шкаф.", motion="The wardrobe shifts slightly, slow push-in."),
        shot("Лестница.", motion="Camera pans slowly to the ceiling."),
    )

    assert [p for p in problems(script, style()) if "camera" in p.lower()] == [
        "Camera moves that make the video model invent what is outside the picture: "
        "shot 1 'tilts', shot 3 'pans'. The camera only holds or pushes in slowly."
    ]


def test_pictures_and_looks_written_in_russian_are_refused() -> None:
    script = flood(shot("Раз."), shot("Два."), shot("Три."))
    script.shots[1].picture = "Открытая дверь соседней квартиры."
    script.characters[0].look = "30 лет, короткие тёмные волосы, синий дождевик"

    assert problems(script, style()) == [
        "Write `picture` and `motion` in English: shots 2.",
        "Write the look of Артём in English; the image model reads English.",
    ]


def test_lines_plates_and_title_in_another_language_are_sent_back() -> None:
    script = flood(
        shot("Cold water rises to his knees."),
        shot("Артём просыпается в темноте, рация шипит."),
        shot("Лена ждёт.", Overlay(kind="goal", text="Floor nine")),
        shot("Мистер Уайт берёт лапу."),
    )
    script.title = "Flood: The Ninth Floor"

    assert problems(script, style(), "ru")[0] == (
        "Not in Russian: the title and shots 1, 3. The title, every line and every plate are "
        "in Russian; only picture, motion, looks and music stay in English."
    )
    assert not [p for p in problems(script, style()) if "Not in" in p]
    assert not [p for p in problems(script, style(), "ja") if "Not in" in p]
    english = flood(shot("Rain."), shot("Wind."), shot("Snow."))
    english.title = "Flood"
    assert problems(english, style(), "en") == []


def test_too_many_empty_shots_in_a_row_are_refused() -> None:
    script = flood(
        shot("Артём просыпается."),
        shot("Дверь.", cast=()),
        shot("Лифт.", cast=()),
        shot("Лестница.", cast=()),
        shot("Артём идёт."),
    )

    assert "Shots 2 to 4 show nobody" in " ".join(problems(script, style()))
    script.shots[2].cast = ["Артём"]
    assert "show nobody" not in " ".join(problems(script, style()))


def test_the_length_read_aloud_holds_short_lines_and_caps_long_ones() -> None:
    long = " ".join(["Артём поднимается по тёмной лестнице и считает ступени вслух"] * 3)

    assert spoken_seconds(flood(shot("Да."), shot("Нет."), shot("Да."))) == 6.0
    assert spoken_seconds(flood(shot(long), shot(long), shot(long))) == 24.0
    assert spoken_seconds(flood(*[shot("Артём открывает дверь и видит воду.")] * 3)) == (
        pytest.approx(3 * (12 / 5.0 + 0.35))
    )


def test_an_episode_that_would_run_past_the_style_limit_is_sent_back() -> None:
    long = " ".join(["Артём поднимается по тёмной лестнице и считает ступени вслух"] * 3)

    too_long = problems(flood(*[shot(long)] * 10), style())
    fits = problems(flood(*[shot("Артём идёт наверх.")] * 10), style())

    assert [p for p in too_long if "runs about" in p] == [
        "Read aloud, the episode runs about 80 s and must stay under 60 s. Cut whole shots "
        "or words until it fits; keep the opening and the last line."
    ]
    assert not [p for p in fits if "runs about" in p]


def test_a_thing_held_in_a_look_would_be_in_every_frame_and_is_sent_back() -> None:
    script = flood(shot("Раз."), shot("Два."), shot("Три."))
    script.characters[0].look = "man, 30, short dark hair, blue raincoat, holding a torch"

    assert problems(script, style()) == [
        "The look of Артём has them 'holding a torch', so it is drawn into every shot they "
        "are in. A look is age, hair, face and clothes; a thing in the hands goes in the "
        "picture of the shot that shows it."
    ]


def test_a_signature_thing_that_is_part_of_the_look_stays() -> None:
    assert problems(flood(shot("Раз."), shot("Два."), shot("Три.")), style()) == []


@pytest.mark.parametrize(
    ("line", "heard", "extra"),
    [
        (
            "Петля сжимает горло в тишине.",
            "Low, Slow, O-. Петля сжимает горло в тишине.",
            "low slow o",
        ),
        (
            "Плантатор думал поджечь мост врагу.",
            "Айтенс виспер. Плантатор думал поджечь мост врагу.",
            "айтенс виспер",
        ),
        (
            "Утром он стоит у ворот дома.",
            "Урк Quiet Relief. Утром он стоит у ворот дома.",
            "урк quiet relief",
        ),
        (
            "Сержант сдвигает доску под ногами.",
            "A sudden. Сержант сдвигает доску под ногами.",
            "a sudden",
        ),
        (
            "Она берет четыреста франков для нового платья.",
            "Она берет 400 франков для нового платья.",
            "",
        ),
        ("Её руки красные и грубые от воды.", "Ее руки красные и грубые от воды.", ""),
        ("В кармане часы тикают всё реже.", "В кармане часы тикают все реже.", ""),
        ("На балу она сияет до четырёх утра.", "На балу она сияет до 4 утра.", ""),
        ("Подруга отдаёт ожерелье не глядя.", "Подруга отдаёт ожерелье, не глядя, и", ""),
        ("Свет гаснет.", "Light. Свет гаснет.", "light"),
    ],
)
def test_a_take_is_misspoken_when_the_narrator_adds_words_to_the_line(
    line: str, heard: str, extra: str
) -> None:
    assert misspoken(line, heard) == extra


def test_more_moving_shots_than_the_style_allows_are_refused() -> None:
    strict = style().model_copy(update={"story": style().story.model_copy(update={"moving": 0.4})})
    script = flood(*[shot("Артём идёт.") for _ in range(5)])

    assert "Shots 1, 2, 3, 4, 5 are marked as moving, and at most 2 may be" in " ".join(
        problems(script, strict)
    )
    for still in script.shots[2:]:
        still.moves = False
    assert "marked as moving" not in " ".join(problems(script, strict))
    assert "marked as moving" not in " ".join(problems(flood(*[shot("Да.")] * 5), style()))


def _skeleton_style(events: int, breaths: int, low: int = 1) -> Style:
    story = style().story.model_copy(
        update={"events": events, "breaths": breaths, "seconds": (low, 600)}
    )
    return style().model_copy(update={"story": story})


def roles(*kinds: str) -> Script:
    script = flood(*[shot("Артём идёт.") for _ in kinds])
    for s, kind in zip(script.shots, kinds, strict=True):
        s.role = kind  # type: ignore[assignment]
    return script


def test_every_episode_has_the_styles_count_of_events_and_breaths() -> None:
    strict = _skeleton_style(events=3, breaths=1)

    found = " ".join(problems(roles("event", "event", "event", "event"), strict))
    assert "4 event and 0 breath shots; this channel needs exactly 3 events and 1 breaths" in found
    assert "event and" not in " ".join(problems(roles("event", "event", "breath", "event"), strict))


def test_the_opening_two_and_the_last_shot_are_events_and_breaths_never_follow_each_other() -> None:
    strict = _skeleton_style(events=2, breaths=3)

    found = " ".join(problems(roles("breath", "event", "breath", "breath", "breath"), strict))
    assert "Shots 1, 5 must be events" in found
    assert "Shots 4, 5 are breaths right after a breath" in found
    loose = " ".join(problems(roles("event", "breath", "breath"), style()))
    assert "Shots 3 are breaths right after a breath" in loose
    assert "must be events" not in loose


def test_an_episode_shorter_than_the_style_allows_is_sent_back() -> None:
    long = _skeleton_style(events=3, breaths=0, low=30)

    assert "must last at least 30 s" in " ".join(problems(roles("event", "event", "event"), long))
    assert "must last at least" not in " ".join(problems(roles("event", "event", "event"), style()))


def test_an_outfit_must_be_declared_and_worn_by_someone_in_the_frame() -> None:
    script = flood(shot("Артём идёт."), shot("Артём идёт."), shot("Артём идёт."))
    script.characters[0].outfits = {"wet": "a soaked grey hoodie"}
    script.shots[1].wears = {"Артём": "wet"}

    assert "`wears`" not in " ".join(problems(script, style()))
    script.shots[2].wears = {"Артём": "suit", "Лена": "wet"}
    found = " ".join(problems(script, style()))
    assert "shot 3 (Артём in 'suit'), shot 3 (Лена in 'wet')" in found
