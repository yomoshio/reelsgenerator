import zipfile
from pathlib import Path

import pytest

from reelsmith.books import cut, digest, make_adaptation, passages, read_book
from reelsmith.models import Adaptation, Character, Outline, Part, Season
from reelsmith.styles import Style
from tests.fakes import style

FB2 = """<?xml version="1.0" encoding="windows-1251"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Лапа</book-title></title-info></description>
<body><title><p>Часть первая</p></title>
<section><p>Ночь, <emphasis>ливень</emphasis>.</p><p>Стук в дверь.</p></section></body>
<body name="notes"><section><p>Примечание переводчика</p></section></body>
</FictionBook>"""

CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest><item id="two" href="two.xhtml"/><item id="one" href="one.xhtml"/></manifest>
<spine><itemref idref="one"/><itemref idref="two"/></spine></package>"""


def test_passages_keep_paragraphs_whole_and_cut_long_ones_between_sentences() -> None:
    long = "Длинное предложение номер раз. " * 10
    text = f"Первый абзац.\n\nВторой абзац.\n\n{long}"

    found = passages(text, size=80)

    assert found[0] == "Первый абзац.\n\nВторой абзац."
    assert all(len(p) <= 80 for p in found)
    assert " ".join(" ".join(found).split()) == " ".join(text.split())
    assert passages("абвгдежзийклмноп", size=10) == ["абвгдежзий", "клмноп"]


def test_books_are_read_from_plain_text_fiction_book_and_epub(tmp_path: Path) -> None:
    old = tmp_path / "old.txt"
    old.write_bytes("Глава один.\n\nГлава два.".encode("cp1251"))
    fb2 = tmp_path / "paw.fb2"
    fb2.write_bytes(FB2.encode("cp1251"))
    epub = tmp_path / "paw.epub"
    with zipfile.ZipFile(epub, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr("META-INF/container.xml", CONTAINER)
        book.writestr("OEBPS/content.opf", OPF)
        book.writestr(
            "OEBPS/one.xhtml", "<html><head><title>x</title></head><body><p>Раз.</p></body></html>"
        )
        book.writestr(
            "OEBPS/two.xhtml",
            "<html><body><script>skip()</script><p>Два,<br/>три.</p></body></html>",
        )

    assert read_book(old) == "Глава один.\n\nГлава два."
    assert read_book(fb2) == "Часть первая\n\nНочь, ливень.\n\nСтук в дверь."
    assert read_book(epub) == "Раз.\n\nДва,\n\nтри."
    with pytest.raises(ValueError, match="fb2"):
        read_book(tmp_path / "paw.pdf")


def test_episodes_cover_every_event_once_in_order_and_stop_at_the_most() -> None:
    parts = [
        Part(title="b", logline="", last=7),
        Part(title="a", logline="", last=3),
        Part(title="same", logline="", last=3),
        Part(title="c", logline="", last=99),
    ]

    assert [(p.title, list(r)) for p, r in cut(parts, 10, most=5)] == [
        ("a", [1, 2, 3]),
        ("b", [4, 5, 6, 7]),
        ("c", [8, 9, 10]),
    ]
    assert [list(r) for _, r in cut(parts, 10, most=2)] == [[1, 2, 3], [4, 5, 6, 7, 8, 9, 10]]


class Book:
    def __init__(self, short_after: int | None = None) -> None:
        self.briefs: list[str] = []
        self.retold = 0
        self.short_after = short_after

    async def retell(self, passage: str) -> list[str]:
        self.retold += 1
        if self.short_after is not None and self.retold > self.short_after:
            return [passage[:30]]
        return [p for p in passage.split("\n\n") if p]

    async def adapt(self, events: list[str], style: Style, most: int) -> Adaptation:
        return Adaptation(
            title="Лапа",
            world="Англия, дом в конце дороги.",
            characters=[Character(name="Уайт", look="man, 60, round spectacles")],
            parts=[
                Part(title="Желание", logline="Уайт загадывает.", last=2),
                Part(title="Стук", logline="Стучат.", last=3),
            ],
        )

    async def plan(self, idea: str, style: Style) -> Outline:
        self.briefs.append(idea)
        return Outline(
            title=idea[:20],
            characters=[Character(name="Уайт", look="man, 60, round spectacles")],
            beats=["a", "b", "c", "d"],
            planted="лапа",
            ending="Дорога пуста.",
        )

    async def season(self, synopsis: str, style: Style, episodes: int) -> Season:
        raise AssertionError("an adaptation plans no season of its own")


async def test_each_episode_is_outlined_from_its_own_events_only() -> None:
    book = Book()
    text = "Уайт загадывает двести фунтов.\n\nСын погибает на фабрике.\n\nНочью стучат в дверь."

    serial = await make_adaptation(book, text, style(), most=5)

    assert [e.title for e in serial.season.episodes] == ["Желание", "Стук"]
    first, second = book.briefs
    assert "1) Уайт загадывает двести фунтов. 2) Сын погибает на фабрике." in first
    assert "Ночью стучат" not in first
    assert second.endswith("add no event of your own: 3) Ночью стучат в дверь.")


async def test_a_long_book_is_retold_again_until_the_planner_can_read_it() -> None:
    text = "\n\n".join(f"Событие номер {n} в долгой книге." for n in range(1500))
    first_pass = len(passages(text))
    book = Book(short_after=first_pass)

    events = await digest(book, text)

    assert book.retold > first_pass
    assert len(events) == book.retold - first_pass
    assert all(len(e) <= 30 for e in events)
