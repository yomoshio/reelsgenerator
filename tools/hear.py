"""Reads lines aloud twice, as written and with the stresses marked, so the two can be heard
side by side. Each line of the file becomes NN-plain.wav and NN-stressed.wav, and marks.txt
says what the reader was given.

    python tools/hear.py lines.txt --out outbox/ударения

The voice service must be up (`./run.sh up`, or the tunnel to the box)."""

import argparse
import asyncio
from pathlib import Path

from reelsmith.settings import Settings
from reelsmith.stress import fixes, kept, pinned
from reelsmith.voice import Speech


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("lines", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voice", default="narrator")
    args = parser.parse_args()
    settings = Settings()
    speech = Speech(settings.speech_url, reader=settings.reader())
    known = fixes(settings.stress)
    args.out.mkdir(parents=True, exist_ok=True)
    marks = []
    texts = [t.strip() for t in args.lines.read_text(encoding="utf-8").splitlines() if t.strip()]
    for n, text in enumerate(texts, 1):
        marked = pinned(kept(text, await speech.stress(text, settings.language)), known)
        marks.append(f"{n:02d} {marked}")
        for name, said in (("plain", text), ("stressed", marked)):
            take = await speech.speak(said, args.voice, settings.language)
            (args.out / f"{n:02d}-{name}.wav").write_bytes(take)
        print(marks[-1])
    (args.out / "marks.txt").write_text("\n".join(marks) + "\n", encoding="utf-8")
    await speech.close()


if __name__ == "__main__":
    asyncio.run(main())
