"""One-call helper: search -> resolve -> download audio + cover.

This is the piece a bot usually wants. It uses the direct audio stream when
possible (no intermediate video download) and falls back to yt-dlp's downloader
when the stream cannot be piped.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from .client import YouTube
from .errors import DownloadError


@dataclass
class Fetched:
    """Everything a bot needs to post a track to a chat."""

    title: str
    artist: Optional[str]
    duration: Optional[float]
    audio_path: str
    cover_path: Optional[str]
    source_url: str
    video_id: str


def _safe_name(text: str, max_len: int = 80) -> str:
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:max_len] or "audio"


class Fetcher:
    """High-level fetch that produces a ready-to-send audio file + cover."""

    def __init__(self, youtube: Optional[YouTube] = None, **youtube_kwargs) -> None:
        self.yt = youtube or YouTube(**youtube_kwargs)

    def fetch(
        self,
        query: str,
        *,
        out_dir: str = "downloads",
        fmt: str = "mp3",
        bitrate: str = "192k",
        with_cover: bool = True,
        prefer_stream: bool = True,
        filename: Optional[str] = None,
    ) -> Fetched:
        """Search (if needed), download the audio and optionally the cover.

        ``query`` may be a search text, a video id or a full URL.
        """
        os.makedirs(out_dir, exist_ok=True)

        track = None
        if re.match(r"^[A-Za-z0-9_-]{11}$", query.strip()) or query.strip().startswith("http"):
            try:
                track = self.yt.get(query)
            except DownloadError:
                track = None
        if track is None:
            track = self.yt.search_one(query)
        if track is None:
            raise DownloadError(f"nothing found for {query!r}")

        name = filename or _safe_name(f"{track.uploader or ''} - {track.title}".strip(" -"))
        audio_path = os.path.join(out_dir, f"{name}.{fmt}")

        if prefer_stream and track.audio_url:
            try:
                self.yt.ffmpeg.convert(
                    track.audio_url,
                    audio_path,
                    fmt=fmt,
                    bitrate=bitrate,
                    http_headers=track.audio_headers,
                    cookie_header=self.yt._cookie_header(),
                )
            except Exception:  # noqa: BLE001 - fall back to the downloader
                audio_path = self.yt.download(
                    track.id, out_dir=out_dir, fmt=fmt, bitrate=bitrate, filename=name
                )
        else:
            audio_path = self.yt.download(
                track.id, out_dir=out_dir, fmt=fmt, bitrate=bitrate, filename=name
            )

        cover_path = None
        if with_cover:
            try:
                cover_path = self.yt.download_cover(track.id, out_dir=out_dir)
            except Exception:  # noqa: BLE001 - cover is optional
                cover_path = None

        return Fetched(
            title=track.title,
            artist=track.uploader,
            duration=track.duration,
            audio_path=audio_path,
            cover_path=cover_path,
            source_url=track.watch_url,
            video_id=track.id,
        )
