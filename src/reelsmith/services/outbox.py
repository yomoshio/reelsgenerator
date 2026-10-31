import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from reelsmith.models import Post


class OutboxPublisher:
    """Drops the cut and its caption into a folder.

    TikTok keeps API posts private until the app passes its audit, so the first version
    stops here and a person uploads from the outbox. A TikTok or Instagram publisher
    implements the same `publish` and replaces this one in `app.py`."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    async def publish(self, video: Path, post: Post) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = self._folder / f"{stamp}-{video.parent.name[:8]}"
        target.mkdir(parents=True, exist_ok=False)
        shutil.copy2(video, target / "video.mp4")
        meta = {"caption": post.caption, "hook_kind": post.hook_kind, "is_aigc": post.ai_generated}
        (target / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return str(target)
