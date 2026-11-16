"""ytpush: search, inspect and download YouTube audio.

A small, self-contained wrapper around yt-dlp + ffmpeg for bots that need a
track's audio, thumbnail and cover image.

Quick start::

    from ytpush import YouTube

    yt = YouTube()
    track = yt.search_one("daft punk instant crush")
    print(track.title, track.duration_str, track.thumbnail)

    path = yt.download(track.id, out_dir="downloads", fmt="mp3")
    cover = yt.download_cover(track.id, out_dir="downloads")

Or hand a stream URL straight to your own ffmpeg pipeline::

    url = yt.stream_url(track.id)

Respect YouTube's Terms of Service and copyright: use this for content you own
or that is licensed for reuse.
"""

from __future__ import annotations

from .backend import YtDlpBackend
from .client import YouTube, normalize_target
from .errors import DownloadError, FFmpegError, FFmpegNotFound, YtpushError
from .fetcher import Fetched, Fetcher
from .ffmpeg import FFmpeg, find_ffmpeg, find_ffprobe, read_cookiefile
from .models import Thumbnail, Track

__version__ = "0.1.0"

__all__ = [
    "YouTube",
    "Fetcher",
    "Fetched",
    "normalize_target",
    "Track",
    "Thumbnail",
    "YtDlpBackend",
    "FFmpeg",
    "find_ffmpeg",
    "find_ffprobe",
    "read_cookiefile",
    "YtpushError",
    "DownloadError",
    "FFmpegError",
    "FFmpegNotFound",
    "__version__",
]
