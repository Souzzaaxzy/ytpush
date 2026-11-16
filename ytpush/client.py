"""The public client: search, inspect and download YouTube audio."""

from __future__ import annotations

import os
import re
from typing import List, Optional

from .backend import YtDlpBackend
from .errors import DownloadError, YtpushError
from .ffmpeg import FFmpeg, find_ffmpeg
from .models import Track

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_target(value: str) -> str:
    """Accept a video id, a watch URL, youtu.be link or a search query.

    Bare ids and URLs are turned into a canonical watch URL; anything else is
    passed through as a search query.
    """
    value = value.strip()
    if _VIDEO_ID.match(value):
        return f"https://www.youtube.com/watch?v={value}"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return value


class YouTube:
    """High level entry point.

    >>> yt = YouTube()
    >>> tracks = yt.search("daft punk instant crush", limit=1)
    >>> tracks[0].title
    '...'
    >>> path = yt.download(tracks[0].id, fmt="mp3")   # doctest: +SKIP
    """

    def __init__(
        self,
        backend=None,
        ffmpeg: Optional[FFmpeg] = None,
        *,
        ffmpeg_location: Optional[str] = None,
        cookiefile: Optional[str] = None,
        cookies_from_browser: Optional[str] = None,
        player_client: Optional[str] = None,
    ) -> None:
        self._ffmpeg_location = ffmpeg_location
        self.cookiefile = cookiefile
        self.backend = backend or YtDlpBackend(
            ffmpeg_location=ffmpeg_location,
            cookiefile=cookiefile,
            cookies_from_browser=cookies_from_browser,
            player_client=player_client,
        )
        self._ffmpeg = ffmpeg

    def _cookie_header(self) -> Optional[str]:
        if not self.cookiefile:
            return None
        from .ffmpeg import read_cookiefile

        return read_cookiefile(self.cookiefile)

    # -- ffmpeg (lazy so importing the lib needs no ffmpeg) --------------
    @property
    def ffmpeg(self) -> FFmpeg:
        if self._ffmpeg is None:
            self._ffmpeg = FFmpeg(ffmpeg=self._ffmpeg_location)
        return self._ffmpeg

    # -- reads -----------------------------------------------------------
    def search(self, query: str, *, limit: int = 10) -> List[Track]:
        """Search YouTube and return up to ``limit`` tracks."""
        info = self.backend.extract(f"ytsearch{limit}:{query}")
        if not info:
            return []
        entries = info.get("entries") or []
        return [Track.from_info(e) for e in entries if e]

    def search_one(self, query: str, *, attempts: int = 3) -> Optional[Track]:
        """Return the single best match, or ``None``.

        Searches a few results and returns the first that actually resolves to a
        playable track, so one unavailable video does not sink the lookup.
        """
        results = self.search(query, limit=max(1, attempts))
        return results[0] if results else None

    def get(self, target: str) -> Track:
        """Fetch metadata for a video id or URL."""
        info = self.backend.extract(normalize_target(target))
        if info is None:
            raise DownloadError(
                f"no data for {target!r}; the video may be unavailable, private or "
                "blocked (YouTube sometimes asks a datacenter IP to confirm it is not a bot)"
            )
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                raise DownloadError(f"no usable entries for {target!r}")
            info = entries[0]
        return Track.from_info(info)

    def stream_url(self, target: str) -> Optional[str]:
        """Return a direct audio stream URL (googlevideo), if available.

        Handy when you want to pipe the audio straight to ffmpeg without
        writing an intermediate file.
        """
        return self.get(target).audio_url

    def thumbnail(self, target: str) -> Optional[str]:
        """Return the best thumbnail URL for a video."""
        return self.get(target).thumbnail

    def convert_stream(
        self,
        target: str,
        out_path: str,
        *,
        fmt: Optional[str] = None,
        bitrate: str = "192k",
        duration: Optional[float] = None,
        normalize: bool = False,
    ) -> str:
        """Pipe a video's audio stream straight into ffmpeg.

        Faster than downloading the whole video: ffmpeg reads the audio URL
        directly, sending the headers YouTube's CDN requires. Falls back to
        :meth:`download` if the stream cannot be piped.
        """
        track = self.get(target)
        if not track.audio_url:
            return self.download(target, out_dir=os.path.dirname(out_path) or ".", fmt=fmt or "mp3", bitrate=bitrate)
        try:
            return self.ffmpeg.convert(
                track.audio_url,
                out_path,
                fmt=fmt,
                bitrate=bitrate,
                duration=duration,
                normalize=normalize,
                http_headers=track.audio_headers,
                cookie_header=self._cookie_header(),
            )
        except YtpushError:
            return self.download(
                target, out_dir=os.path.dirname(out_path) or ".", fmt=fmt or "mp3", bitrate=bitrate
            )

    # -- downloads -------------------------------------------------------
    def download(
        self,
        target: str,
        *,
        out_dir: str = ".",
        fmt: str = "mp3",
        bitrate: str = "192k",
        filename: Optional[str] = None,
        normalize: bool = False,
    ) -> str:
        """Download the audio of ``target`` and return the output file path.

        ``fmt`` selects the output container/codec (``mp3``, ``m4a``, ``opus``,
        ``wav``...). The audio is re-encoded with ffmpeg, so the result plays
        anywhere.
        """
        os.makedirs(out_dir, exist_ok=True)
        template = os.path.join(out_dir, (filename or "%(id)s") + ".%(ext)s")
        postprocessors = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": bitrate.rstrip("k"),
            }
        ]
        path = self.backend.download(
            normalize_target(target),
            outtmpl=template,
            format_selector="bestaudio/best",
            postprocessors=postprocessors,
        )
        if normalize:
            normalized = os.path.splitext(path)[0] + f".norm.{fmt}"
            self.ffmpeg.convert(path, normalized, fmt=fmt, bitrate=bitrate, normalize=True)
            os.replace(normalized, path)
        return path

    def download_audio(
        self,
        target: str,
        *,
        out_dir: str = ".",
        fmt: str = "mp3",
        bitrate: str = "192k",
        normalize: bool = False,
    ) -> str:
        """Alias of :meth:`download` with an explicit name."""
        return self.download(target, out_dir=out_dir, fmt=fmt, bitrate=bitrate, normalize=normalize)

    def download_cover(self, target: str, *, out_dir: str = ".", width: int = 640) -> str:
        """Download the thumbnail image for a video and return its path."""
        import urllib.request

        track = self.get(target)
        if not track.thumbnail:
            raise YtpushError(f"no thumbnail for {target!r}")
        os.makedirs(out_dir, exist_ok=True)
        ext = "webp" if track.thumbnail.endswith(".webp") else "jpg"
        out = os.path.join(out_dir, f"{track.id}.{ext}")
        req = urllib.request.Request(track.thumbnail, headers={"User-Agent": "ytpush/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(out, "wb") as fh:
            fh.write(resp.read())
        return out
