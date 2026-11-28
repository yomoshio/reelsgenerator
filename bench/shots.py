"""Writes the tests for an episode from its shot list: one test a beat, for one way of making it.

    python3 bench/shots.py bench/tests/paw.json refs            pictures of the cast and the place
    python3 bench/shots.py bench/tests/paw.json h3-r2v          MiniMax H3 led by those pictures
    python3 bench/shots.py bench/tests/paw.json h3-t2v --turbo  MiniMax H3 from text alone, 8 steps
    python3 bench/shots.py bench/tests/paw.json ltx-t2v --beats 1 5 9

The list goes to bench/tests/<episode>-<way>.json; bench/run.py runs it with
--out bench/out/<episode>-<way>, and bench/episode.py joins that folder with the voice. A beat
is as long as its line in the job's voice/timing.json, and never shorter than the model can make."""

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORTRAIT = "9:16 (Portrait Widescreen)"
QUIET = "No speech, no narration, no singing and no music."
CLEAN = (
    "No text, captions, subtitles, logos or watermarks anywhere. Vertical frame: faces and the "
    "main action stay in the upper two thirds."
)
SHEETS = {
    "person": "Character reference: full-length view of {look}, standing, turned three-quarters "
              "to the viewer, calm face. The background is one flat pale grey with nothing in it: "
              "no room, no street, no fire, no rain.",
    "place": "Wide establishing view of {look}. Nobody in the room.",
    "thing": "Close view of {look}, lying on a dark wooden table under a warm lamp.",
}  # fmt: skip


def kind(subject: dict) -> str:
    return "place" if subject.get("place") else "thing" if subject.get("thing") else "person"


def timed(shots: list, seconds: float) -> str:
    lines, at = [], 0.0
    for n, (share, text) in enumerate(shots, 1):
        lines.append(f"[{at:.1f}s-{at + share * seconds:.1f}s] Shot {n}: {text}.")
        at += share * seconds
    return "\n".join(lines)


def led(story: dict, beat: dict, seconds: float) -> str:
    """A prompt in the form MiniMax H3 was shown with reference pictures."""
    told = []
    for n, key in enumerate(beat["who"], 1):
        subject = story["subjects"][key]
        role = {"person": "is", "place": "is the place,", "thing": "is the thing,"}[kind(subject)]
        told.append(f"<Picture {n}> {role} {subject['name']}: {subject['look']}.")
    return "\n\n".join([
        story["style"],
        "subject_definitions:\n" + "\n".join(told),
        f"Scene overview: {beat['scene']} Everyone and everything looks as in the pictures.",
        "Storyboard:\n" + timed(beat["shots"], seconds),
        f"Audio: {beat['audio']}. {QUIET}",
        CLEAN,
    ])  # fmt: skip


def plain(story: dict, beat: dict, seconds: float) -> str:
    """A prompt for a model that sees no pictures: everyone is described in words."""
    looks = " ".join(
        f"{story['subjects'][key]['name'][0].upper()}{story['subjects'][key]['name'][1:]} is "
        f"{story['subjects'][key]['look']}."
        for key in beat["who"]
    )
    return "\n\n".join([
        story["style"],
        f"Scene overview: {beat['scene']} {looks}",
        "Storyboard:\n" + timed(beat["shots"], seconds),
        f"Audio: {beat['audio']}. {QUIET}",
        CLEAN,
    ])  # fmt: skip


def tests(story: dict, way: str, args: argparse.Namespace) -> list[dict]:
    size = [["ResolutionSelector", "aspect_ratio", PORTRAIT],
            ["ResolutionSelector", "megapixels", args.megapixels],
            ["ResolutionSelector", "multiple", 32]]  # fmt: skip
    if way == "refs":
        return [
            {"name": key, "workflow": "image_minimax_h3_t2i", "seed": args.seed,
             "set": [*size, ["CLIPTextEncode", "text",
                     f"{story['sheet_style' if kind(subject) == 'person' else 'style']}\n\n"
                     f"{SHEETS[kind(subject)].format(look=subject['look'])}\n\n{CLEAN}"]]}
            for key, subject in story["subjects"].items()
        ]  # fmt: skip
    timing = json.loads((HERE.parent / story["job"] / "voice" / "timing.json").read_text("utf-8"))
    out = []
    for n, (beat, said) in enumerate(zip(story["beats"], timing["beats"], strict=True), 1):
        if args.beats and n not in args.beats:
            continue
        test: dict = {"name": f"beat{n:02d}", "seed": args.seed + n}
        if way.startswith("h3"):
            seconds = max(5.0, said["seconds"])
            turbo = [["Boolean (Enable Lightning LoRA)", "value", args.turbo]]
            if way == "h3-r2v":
                test |= {
                    "workflow": "video_minimax_h3_r2v",
                    "refs": [f"out/{args.refs}/{key}.png" for key in beat["who"]],
                    "set": [*size, *turbo, ["Float (Duration)", "value", seconds],
                            ["Input Text (Prompt)", "value", led(story, beat, seconds)]],
                }  # fmt: skip
            else:
                test |= {
                    "workflow": "video_minimax_h3_t2v",
                    "set": [*size, *turbo, ["Float (duration)", "value", seconds],
                            ["MiniMaxH3ImageToVideo", "prompt", plain(story, beat, seconds)]],
                }  # fmt: skip
        else:
            seconds = math.ceil(said["seconds"])
            test |= {
                "workflow": "video_ltx2_5_t2v",
                "set": [*size, ["Duration", "value", seconds],
                        ["Prompt", "value", plain(story, beat, float(seconds))],
                        ["CLIPTextEncode#2", "text", "blurry, deformed hands, text"]],
            }  # fmt: skip
        out.append(test)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("story", type=Path)
    parser.add_argument("way", choices=["refs", "h3-r2v", "h3-t2v", "ltx-t2v"])
    parser.add_argument("--beats", type=int, nargs="*", help="only these beats, counted from 1")
    parser.add_argument("--turbo", action="store_true", help="MiniMax H3 with its few-step LoRA")
    parser.add_argument("--megapixels", type=float, default=0.98)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--refs", default="refs", help="the folder in bench/out with the pictures")
    parser.add_argument("--tag", default="", help="added to the list's name")
    args = parser.parse_args()
    story = json.loads(args.story.read_text(encoding="utf-8"))
    target = args.story.with_name(f"{args.story.stem}-{args.way}{args.tag}.json")
    made = tests(story, args.way, args)
    target.write_text(json.dumps(made, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{target}: {len(made)} tests")


if __name__ == "__main__":
    main()
