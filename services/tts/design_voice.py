"""Makes the narrator's reference clip from a text description, with no recording needed.

python design_voice.py NAME "description of the voice" [--takes 3]

VoxCPM2 can invent a voice from a description in brackets before the text. A voice invented
fresh on every call would change from shot to shot, so the result is saved as a reference
clip: from then on the service clones that clip. Listen to the takes in /voices and copy
the one you like over `NAME.wav` and `NAME.txt`.
"""

import argparse
import os
from pathlib import Path

import soundfile as sf
from voxcpm import VoxCPM

MODEL_ID = os.environ.get("VOXCPM_MODEL", "openbmb/VoxCPM2")
VOICES = Path(os.environ.get("VOICES_DIR", "/voices"))
# The cloned voice inherits the reference's delivery, so the sample is told, not read:
# short and long sentences, a held pause, a question, a sudden turn.
SAMPLE = (
    "Свет гаснет. Совсем. Он стоит в темноте и слушает… Тишина. А потом — шаги. "
    "Медленные, тяжёлые, всё ближе. Кто там? Никто не отвечает. "
    "И тогда он понимает: шаги идут не снаружи. Они уже внутри!"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("description")
    parser.add_argument("--takes", type=int, default=3)
    parser.add_argument(
        "--text", default=SAMPLE, help="what the voice reads; saved as the transcript"
    )
    args = parser.parse_args()

    model = VoxCPM.from_pretrained(MODEL_ID, optimize=False, load_denoiser=False)
    for take in range(1, args.takes + 1):
        audio = model.generate(text=f"({args.description}){args.text}", cfg_value=2.0)
        stem = VOICES / f"{args.name}-take{take}"
        sf.write(stem.with_suffix(".wav"), audio, model.tts_model.sample_rate)
        stem.with_suffix(".txt").write_text(args.text + "\n", encoding="utf-8")
        print(f"wrote {stem}.wav  {len(audio) / model.tts_model.sample_rate:.1f}s", flush=True)

    first = VOICES / f"{args.name}-take1"
    for suffix in (".wav", ".txt"):
        (VOICES / f"{args.name}{suffix}").write_bytes(first.with_suffix(suffix).read_bytes())
    print(f"{args.name}.wav is take 1; replace it with another take if you prefer")


if __name__ == "__main__":
    main()
