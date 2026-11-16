"""Data models returned by ytpush."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Thumbnail:
    """A single image associated with a video."""

    url: str
    width: Optional[int] = None
    height: Optional[int] = None

    @property
    def resolution(self) -> Optional[str]:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None


@dataclass
class Track:
    """A search result / video, with the fields a bot usually needs."""

    id: str
    title: str
    url: str
    duration: Optional[float] = None          # seconds
    uploader: Optional[str] = None
    thumbnail: Optional[str] = None           # best thumbnail URL
    thumbnails: List[Thumbnail] = field(default_factory=list)
    webpage_url: Optional[str] = None
    audio_url: Optional[str] = None           # direct audio stream (googlevideo)
    audio_format: Optional[str] = None        # e.g. "m4a", "opus", "webm"
    audio_bitrate: Optional[float] = None     # kbps
    audio_headers: dict = field(default_factory=dict)  # required to fetch audio_url
    filesize: Optional[int] = None            # bytes, if known
    license: Optional[str] = None             # e.g. "Creative Commons Attribution"
    is_live: bool = False
    description: Optional[str] = None

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "0:00"
        total = int(self.duration)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def embed_url(self) -> str:
        return f"https://www.youtube.com/embed/{self.id}"

    @property
    def watch_url(self) -> str:
        return self.webpage_url or f"https://www.youtube.com/watch?v={self.id}"

    @classmethod
    def from_info(cls, info: dict) -> "Track":
        """Build a Track from a yt-dlp info dict."""
        thumbs = [
            Thumbnail(url=t.get("url"), width=t.get("width"), height=t.get("height"))
            for t in (info.get("thumbnails") or [])
            if t.get("url")
        ]
        best = _best_audio(info.get("formats") or [])
        return cls(
            id=info.get("id", ""),
            title=info.get("title") or info.get("id", ""),
            url=info.get("webpage_url") or info.get("url") or "",
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("channel"),
            thumbnail=info.get("thumbnail") or (thumbs[-1].url if thumbs else None),
            thumbnails=thumbs,
            webpage_url=info.get("webpage_url"),
            audio_url=best.get("url"),
            audio_format=best.get("ext"),
            audio_bitrate=best.get("abr"),
            audio_headers=dict(best.get("http_headers") or {}),
            filesize=best.get("filesize") or best.get("filesize_approx"),
            license=info.get("license"),
            is_live=bool(info.get("is_live")),
            description=info.get("description"),
        )


def _best_audio(formats: List[dict]) -> dict:
    """Pick the audio-only format with the highest bitrate."""
    audio = [
        f for f in formats
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]
    if not audio:  # fall back to any format that carries audio
        audio = [f for f in formats if f.get("acodec") not in (None, "none")]
    if not audio:
        return {}
    return max(audio, key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0))
