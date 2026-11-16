"""ffmpeg/ffprobe helpers: locate the binary and run conversions.

ffmpeg is looked up in this order:

1. the ``ffmpeg`` argument (explicit path),
2. ``$FFMPEG_BINARY``,
3. ``ffmpeg`` / ``ffprobe`` on ``PATH``,
4. the binary bundled by ``imageio-ffmpeg`` (a pip-installable static build).

That last fallback means the library works without root or a system package
manager, which matters on locked-down servers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from .errors import FFmpegError, FFmpegNotFound


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _headers_blob(headers: dict) -> str:
    """Format a dict of headers the way ffmpeg's ``-headers`` expects."""
    return "".join(f"{k}: {v}\r\n" for k, v in headers.items())


def read_cookiefile(path: str) -> Optional[str]:
    """Read a Netscape cookie file into a single ``Cookie:`` header value.

    Returns ``None`` when the file has no usable cookies. yt-dlp uses the file
    itself; this is for feeding the same session to ffmpeg.
    """
    pairs = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7 and "youtube" in parts[0]:
                    pairs.append(f"{parts[5]}={parts[6]}")
    except OSError:
        return None
    return "; ".join(pairs) or None


def _from_imageio() -> Optional[str]:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return None


def find_ffmpeg(explicit: Optional[str] = None) -> str:
    """Return a usable ffmpeg path or raise :class:`FFmpegNotFound`."""
    candidates: List[Optional[str]] = [
        explicit,
        os.environ.get("FFMPEG_BINARY"),
        shutil.which("ffmpeg"),
        _from_imageio(),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FFmpegNotFound(
        "ffmpeg not found; install it (apt install ffmpeg), set FFMPEG_BINARY, "
        "or `pip install imageio-ffmpeg`"
    )


def find_ffprobe(explicit: Optional[str] = None) -> Optional[str]:
    """Return an ffprobe path if one exists, else ``None``.

    The imageio-ffmpeg bundle has no ffprobe, so we degrade gracefully and use
    ffmpeg itself for metadata probing when needed.
    """
    candidates = [explicit, os.environ.get("FFPROBE_BINARY"), shutil.which("ffprobe")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


class FFmpeg:
    """Thin wrapper around the ffmpeg/ffprobe binaries."""

    def __init__(self, ffmpeg: Optional[str] = None, ffprobe: Optional[str] = None) -> None:
        self.ffmpeg = find_ffmpeg(ffmpeg)
        self.ffprobe = find_ffprobe(ffprobe)

    def run(self, args: Sequence[str], *, timeout: float = 300.0) -> str:
        """Run ffmpeg with ``args`` and return its combined output."""
        try:
            proc = subprocess.run(
                [self.ffmpeg, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise FFmpegNotFound(f"ffmpeg binary not found: {self.ffmpeg}") from exc
        output = proc.stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            tail = "\n".join(output.strip().splitlines()[-12:])
            raise FFmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
        return output

    def convert(
        self,
        source: str,
        target: str,
        *,
        fmt: Optional[str] = None,
        bitrate: Optional[str] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        start: Optional[float] = None,
        duration: Optional[float] = None,
        normalize: bool = False,
        http_headers: Optional[dict] = None,
        cookie_header: Optional[str] = None,
        extra_args: Sequence[str] = (),
    ) -> str:
        """Convert/extract audio from ``source`` into ``target``.

        ``fmt`` is a container/codec like ``mp3``, ``m4a``, ``opus``, ``wav``.
        ``normalize`` applies EBU R128 loudness normalization. ``http_headers``
        are sent when ``source`` is a URL (YouTube's CDN rejects requests
        without a browser User-Agent). ``cookie_header`` is an optional raw
        ``Cookie:`` value for URLs that require a session.
        """
        args: List[str] = ["-hide_banner", "-loglevel", "error", "-y"]
        if _is_url(source):
            headers = dict(http_headers or {})
            if cookie_header:
                headers["Cookie"] = cookie_header
            if headers:
                args += ["-headers", _headers_blob(headers)]
        if start is not None:
            args += ["-ss", str(start)]
        args += ["-i", source]
        if duration is not None:
            args += ["-t", str(duration)]
        args += ["-vn"]  # drop video: we only want audio
        if normalize:
            args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        if sample_rate:
            args += ["-ar", str(sample_rate)]
        if channels:
            args += ["-ac", str(channels)]
        if bitrate:
            args += ["-b:a", bitrate]
        if fmt:
            args += ["-f", fmt]
        args += list(extra_args)
        args.append(target)
        self.run(args)
        return target

    def duration(self, path: str) -> Optional[float]:
        """Return the media duration in seconds, if it can be determined."""
        if self.ffprobe:
            proc = subprocess.run(
                [
                    self.ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                return float(proc.stdout.decode().strip())
            except (ValueError, AttributeError):
                return None
        # Fallback: parse ffmpeg's stderr banner.
        proc = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        import re

        match = re.search(rb"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stdout)
        if match:
            h, m, s = (float(x) for x in match.groups())
            return h * 3600 + m * 60 + s
        return None

    def make_thumbnail(self, source: str, target: str, *, at: float = 1.0, width: int = 640) -> str:
        """Extract a single frame as an image (useful as a cover for the bot)."""
        self.run(
            [
                "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(at),
                "-i", source,
                "-frames:v", "1",
                "-vf", f"scale={width}:-1",
                target,
            ]
        )
        return target
