import zipfile
from pathlib import Path

import pytest

from reelsmith.books import Part, cut, episodes, passages, read_book
from reelsmith.styles import Styles
from tests.fakes import REPO, FakeLlm, context

STYLE = Styles(REPO / "styles").get("blackout")

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


async def test_a_short_story_stays_one_episode(tmp_path: Path) -> None:
    llm = FakeLlm()
    found = await episodes(context(tmp_path, llm), STYLE, "Короткий рассказ. " * 50, "Рассказ")
    assert [s.kind for s in found] == ["story"]
    assert llm.calls == []


async def test_a_long_story_becomes_one_job_per_part(tmp_path: Path) -> None:
    text = "\n\n".join(f"Абзац {n}. " + "Слово " * 300 for n in range(10))
    events = [f"Событие {n}" for n in range(1, 7)]
    person = {"key": "ivan", "name": "Иван", "look": "a tall man"}
    llm = (
        FakeLlm()
        .answer("Retelling", *[{"events": events[:3]}, {"events": events[3:]}])
        .answer("Adaptation", {"title": "Книга", "world": "Мир.", "characters": [person],
                               "parts": [{"title": "Один", "logline": "Начало.", "last": 3},
                                         {"title": "Два", "logline": "Конец.", "last": 9}]})
    )  # fmt: skip
    found = await episodes(context(tmp_path, llm), STYLE, text, "Книга")
    assert [s.title for s in found] == ["Книга, часть 1", "Книга, часть 2"]
    assert "3) Событие 3" in found[0].text
    assert "4) Событие 4" in found[1].text
    assert "6) Событие 6" in found[1].text
    assert "Earlier parts: Начало." in found[1].text


def test_episodes_cover_every_event_once_in_order() -> None:
    parts = [Part(title="b", logline="", last=7), Part(title="a", logline="", last=3),
             Part(title="x", logline="", last=3), Part(title="z", logline="", last=99)]  # fmt: skip
    pieces = cut(parts, 10, 2)
    assert [list(r) for _, r in pieces] == [[1, 2, 3], list(range(4, 11))]
