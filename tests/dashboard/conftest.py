import json

import pytest

from shorts.models import TopicStatus, VideoFormat, VideoStatus
from shorts.publish.youtube import Channel, UploadResult
from shorts.storage.db import connect
from shorts.storage.repositories import VideoRepository
from shorts.storage.topics import TopicRepository


class FakeAccount:
    def __init__(self, channel=Channel("UC1", "Tech Bits"), privacy="public", error=None):
        self._channel, self.privacy, self.error, self.uploads = channel, privacy, error, []

    def channel(self):
        return self._channel

    def upload(self, video_path, body):
        if self.error:
            raise self.error
        self.uploads.append((video_path, body))
        return UploadResult("abcdefghijk", self.privacy)


@pytest.fixture
def make_ready_video(settings):
    """A rendered video awaiting approval, with its export folder and topic row."""

    def _make(title="RTX 5090 announced", status=VideoStatus.AWAITING_APPROVAL):
        conn = connect(settings.data_dir / "shorts.db")
        repo = VideoRepository(conn)
        vid = repo.create(f"https://nvidianews.nvidia.com/{title}", None, VideoFormat.NEWS_FLASH)
        export = settings.data_dir / "exports" / str(vid)
        export.mkdir(parents=True)
        video, meta = export / "video.mp4", export / "metadata.json"
        video.write_bytes(bytes(range(256)) * 4)
        meta.write_text(json.dumps({"title": title, "description": f"About {title}\n\n#NVIDIA",
                                    "hashtags": ["#NVIDIA"], "title_options": [title]}))
        repo.save_script(vid, "{}", title)
        repo.save_output(vid, video, meta, "hash")
        path = ["fact_checked", "rendering", "awaiting_approval"]
        if status == VideoStatus.FAILED:
            path = ["failed"]
        for step in path:
            repo.set_status(vid, VideoStatus(step))
        if status in (VideoStatus.APPROVED, VideoStatus.DISCARDED):
            repo.set_status(vid, status)
        topics = TopicRepository(conn)
        from datetime import UTC, datetime
        tid = topics.record(f"https://nvidianews.nvidia.com/{title}", "NVIDIA Newsroom", title,
                            datetime.now(UTC), TopicStatus.MADE, 0.81, "fresh, 2 sources")
        topics.link_video(tid, vid, TopicStatus.MADE)
        conn.close()
        return vid

    return _make
