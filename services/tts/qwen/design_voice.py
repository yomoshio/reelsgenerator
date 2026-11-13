"""Makes the narrator's reference clip from a text description, with no recording needed.

python design_voice.py NAME "description of the voice" [--takes 3]

Qwen3-TTS VoiceDesign invents a voice from a description. A voice invented fresh on every
call would change from shot to shot, so the result is saved as a reference clip, and the
service clones it with the Base model from then on. Listen to the takes in /voices and
copy the one you like over `NAME.wav` and `NAME.txt`. The description works best in
English: who speaks, the age and timbre, and how they tell.
"""

import argparse
import os
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

MODEL_ID = os.environ.get("QWEN_TTS_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
LANGUAGE = os.environ.get("QWEN_TTS_LANGUAGE", "Russian")
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

    model = Qwen3TTSModel.from_pretrained(MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16)
    for take in range(1, args.takes + 1):
        torch.manual_seed(take)
        wavs, rate = model.generate_voice_design(
            text=args.text, language=LANGUAGE, instruct=args.description
        )
        stem = VOICES / f"{args.name}-take{take}"
        sf.write(stem.with_suffix(".wav"), wavs[0], rate)
        stem.with_suffix(".txt").write_text(args.text + "\n", encoding="utf-8")
        print(f"wrote {stem}.wav  {len(wavs[0]) / rate:.1f}s", flush=True)

    first = VOICES / f"{args.name}-take1"
    for suffix in (".wav", ".txt"):
        (VOICES / f"{args.name}{suffix}").write_bytes(first.with_suffix(suffix).read_bytes())
    print(f"{args.name}.wav is take 1; replace it with another take if you prefer")


if __name__ == "__main__":
    main()
