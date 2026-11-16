"""Errors raised by ytpush."""

from __future__ import annotations


class YtpushError(Exception):
    """Base class for every ytpush error."""


class DownloadError(YtpushError):
    """A download or extraction failed."""


class FFmpegError(YtpushError):
    """An ffmpeg/ffprobe command failed."""


class FFmpegNotFound(FFmpegError):
    """ffmpeg could not be located."""
