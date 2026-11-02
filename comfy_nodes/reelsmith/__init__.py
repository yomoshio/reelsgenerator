"""Reelsmith blocks for the ComfyUI editor: start a video or a whole serial from a sentence
or a story, see what the conveyor is doing, approve a finished video.

A block never waits for the video. It drops a request into the studio inbox and returns at
once: the conveyor needs this same ComfyUI queue to draw frames and clips, so a block that
waited would block it. The worker picks requests up between turns, writes its status to
studio/status.txt, and copies every finished video to output/reelsmith/videos, where the
Assets panel shows it."""

import json
import os
import time
import uuid
from pathlib import Path

STUDIO = Path(os.environ.get("REELSMITH_STUDIO", "/opt/comfy/reelsmith-studio"))
STYLES = Path(os.environ.get("REELSMITH_STYLES", "/opt/comfy/reelsmith-styles"))

ANIMATION = {
    "Wan на движении, наезд на остальном": "hybrid",
    "только наезд камеры, быстро": "still",
    "Wan на каждом шоте, долго": "wan",
}


def styles() -> list[str]:
    found = sorted(p.stem for p in STYLES.glob("*.toml"))
    return found or ["serial"]


def drop(request: dict[str, object]) -> str:
    """Writes the request where the worker looks for it; the rename makes it appear whole."""
    inbox = STUDIO / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # Nanoseconds keep requests in the order they were made; the worker reads them sorted.
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9:09d}-{uuid.uuid4().hex[:4]}"
    partial = inbox / f"{name}.part"
    partial.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    partial.rename(inbox / f"{name}.json")
    return name


def status() -> str:
    path = STUDIO / "status.txt"
    if not path.exists():
        return "Воркер ещё не писал статус: он запущен? Проверьте `docker compose ps`."
    return path.read_text(encoding="utf-8")


def _text(value: str, what: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"Впишите {what}.")
    return text


class ReelsmithVideo:
    CATEGORY = "Reelsmith"
    FUNCTION = "start"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ответ",)
    DESCRIPTION = "Ставит в очередь ролик из одной фразы или из рассказа на несколько сотен слов."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "story": (
                    "STRING",
                    {"multiline": True, "placeholder": "Одна фраза или рассказ на 200 слов"},
                ),
                "style": (styles(),),
                "animation": (list(ANIMATION),),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **_: object) -> float:
        return float("nan")

    def start(self, story: str, style: str, animation: str) -> tuple[str]:
        text = _text(story, "идею или рассказ")
        name = drop(
            {"kind": "video", "story": text, "style": style, "animation": ANIMATION[animation]}
        )
        return (
            f"Заявка {name} отправлена. Воркер возьмёт её в течение минуты. Кадры и клипы "
            "появятся в очереди справа, готовый ролик в Ассетах: reelsmith/videos.",
        )


class ReelsmithSeries:
    CATEGORY = "Reelsmith"
    FUNCTION = "start"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ответ",)
    DESCRIPTION = "Делает из синопсиса серию выпусков и, если нужно, ставит их все в очередь."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "synopsis": ("STRING", {"multiline": True, "placeholder": "Синопсис сезона"}),
                "name": ("STRING", {"default": "series"}),
                "episodes": ("INT", {"default": 10, "min": 1, "max": 30}),
                "style": (styles(),),
                "animation": (list(ANIMATION),),
                "queue_all": ("BOOLEAN", {"default": False, "label_on": "сразу в очередь"}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **_: object) -> float:
        return float("nan")

    def start(
        self, synopsis: str, name: str, episodes: int, style: str, animation: str, queue_all: bool
    ) -> tuple[str]:
        text = _text(synopsis, "синопсис")
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip()) or "series"
        drop(
            {
                "kind": "series",
                "story": text,
                "name": slug,
                "episodes": episodes,
                "style": style,
                "animation": ANIMATION[animation],
                "queue": queue_all,
            }
        )
        then = "и все выпуски встанут в очередь" if queue_all else "выпуски можно поставить потом"
        return (
            f"Серия {slug}: план появится в studio/series/{slug}.md через несколько минут, {then}.",
        )


class ReelsmithStatus:
    CATEGORY = "Reelsmith"
    FUNCTION = "read"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("статус",)
    DESCRIPTION = "Что делает конвейер: последние задачи, их статусы и где готовые ролики."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {"required": {}}

    @classmethod
    def IS_CHANGED(cls, **_: object) -> float:
        return float("nan")

    def read(self) -> tuple[str]:
        return (status(),)


class ReelsmithApprove:
    CATEGORY = "Reelsmith"
    FUNCTION = "approve"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ответ",)
    DESCRIPTION = "Одобряет собранный ролик: он уйдёт в outbox/ вместе с подписью."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {"required": {"job": ("STRING", {"placeholder": "первые 8 знаков id из статуса"})}}

    @classmethod
    def IS_CHANGED(cls, **_: object) -> float:
        return float("nan")

    def approve(self, job: str) -> tuple[str]:
        drop({"kind": "approve", "job": _text(job, "id задачи")})
        return (f"Одобрение {job.strip()} отправлено.",)


class ReelsmithPause:
    CATEGORY = "Reelsmith"
    FUNCTION = "switch"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ответ",)
    DESCRIPTION = "Ставит конвейер на паузу и освобождает видеокарту для работы руками."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "pause": (
                    "BOOLEAN",
                    {"default": True, "label_on": "пауза", "label_off": "работать"},
                )
            }
        }

    @classmethod
    def IS_CHANGED(cls, **_: object) -> float:
        return float("nan")

    def switch(self, pause: bool) -> tuple[str]:
        drop({"kind": "pause" if pause else "resume"})
        if pause:
            return ("Пауза: текущий шаг доделается, новые не начнутся, видеокарта освободится.",)
        return ("Конвейер продолжит работу в течение минуты.",)


NODE_CLASS_MAPPINGS = {
    "ReelsmithVideo": ReelsmithVideo,
    "ReelsmithSeries": ReelsmithSeries,
    "ReelsmithStatus": ReelsmithStatus,
    "ReelsmithApprove": ReelsmithApprove,
    "ReelsmithPause": ReelsmithPause,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ReelsmithVideo": "Reelsmith · Ролик",
    "ReelsmithSeries": "Reelsmith · Серия",
    "ReelsmithStatus": "Reelsmith · Статус",
    "ReelsmithApprove": "Reelsmith · Одобрить",
    "ReelsmithPause": "Reelsmith · Пауза",
}
