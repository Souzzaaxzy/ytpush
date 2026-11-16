"""Offline tests: a fake backend stands in for the network.

Only the yt-dlp boundary is faked; Track parsing, ffmpeg invocation and the
client's logic are the real code.
"""

from __future__ import annotations

import os
import subprocess

import pytest
from ytpush import YouTube, normalize_target
from ytpush.errors import FFmpegError, YtpushError
from ytpush.ffmpeg import FFmpeg
from ytpush.models import Track

VIDEO_INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "duration": 213,
    "uploader": "Rick Astley",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "license": "Creative Commons Attribution",
    "thumbnails": [
        {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg", "width": 120, "height": 90},
        {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "width": 480, "height": 360},
    ],
    "formats": [
        {"acodec": "none", "vcodec": "avc1", "ext": "mp4", "url": "https://video"},
        {"acodec": "mp4a", "vcodec": "none", "ext": "m4a", "url": "https://audio-128", "abr": 128},
        {"acodec": "opus", "vcodec": "none", "ext": "webm", "url": "https://audio-160", "abr": 160},
    ],
}


_UNSET = object()


class FakeBackend:
    """Records calls and returns canned info / a fake downloaded file."""

    def __init__(self, info=_UNSET, path=None):
        self.info = VIDEO_INFO if info is _UNSET else info
        self.path = path
        self.extract_calls = []
        self.download_calls = []

    def extract(self, target):
        self.extract_calls.append(target)
        return self.info

    def _vid(self):
        info = self.info
        if info and info.get("entries"):
            info = info["entries"][0]
        return (info or {}).get("id", "unknown")

    def download(self, target, *, outtmpl, format_selector="bestaudio/best", postprocessors=None, extra_opts=None):
        self.download_calls.append(
            {"target": target, "outtmpl": outtmpl, "format": format_selector, "postprocessors": postprocessors}
        )
        if self.path:
            return self.path
        return outtmpl.replace("%(id)s", self._vid()).replace("%(ext)s", "mp3")


def test_normalize_target():
    assert normalize_target("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert normalize_target("https://youtu.be/dQw4w9WgXcQ") == "https://youtu.be/dQw4w9WgXcQ"
    assert normalize_target("daft punk") == "daft punk"


def test_track_parsing_picks_best_audio():
    t = Track.from_info(VIDEO_INFO)
    assert t.id == "dQw4w9WgXcQ"
    assert t.title.startswith("Rick Astley")
    assert t.duration == 213
    assert t.duration_str == "3:33"
    assert t.audio_url == "https://audio-160"       # highest bitrate audio-only
    assert t.audio_format == "webm"
    assert t.thumbnail.endswith("hqdefault.jpg")
    assert len(t.thumbnails) == 2
    assert t.thumbnails[-1].resolution == "480x360"
    assert t.embed_url == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    assert t.watch_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_track_captures_http_headers():
    info = {
        **VIDEO_INFO,
        "formats": [
            {
                "acodec": "mp4a",
                "vcodec": "none",
                "ext": "m4a",
                "url": "https://audio",
                "abr": 128,
                "http_headers": {"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
            }
        ],
    }
    t = Track.from_info(info)
    assert t.audio_headers == {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}


def test_convert_sends_headers_for_urls(tmp_path, monkeypatch):
    """ffmpeg gets -headers when the source is a URL."""
    from ytpush.ffmpeg import FFmpeg

    ff = FFmpeg.__new__(FFmpeg)
    ff.ffmpeg = "/fake/ffmpeg"
    ff.ffprobe = None
    captured = {}

    def fake_run(args, timeout=300.0):
        captured["args"] = args
        return ""

    monkeypatch.setattr(ff, "run", fake_run)
    ff.convert(
        "https://cdn.example/audio",
        str(tmp_path / "o.mp3"),
        fmt="mp3",
        http_headers={"User-Agent": "Mozilla/5.0"},
    )
    assert "-headers" in captured["args"]
    blob = captured["args"][captured["args"].index("-headers") + 1]
    assert "User-Agent: Mozilla/5.0" in blob


def test_convert_omits_headers_for_local_files(tmp_path, monkeypatch):
    from ytpush.ffmpeg import FFmpeg

    ff = FFmpeg.__new__(FFmpeg)
    ff.ffmpeg = "/fake/ffmpeg"
    ff.ffprobe = None
    captured = {}
    monkeypatch.setattr(ff, "run", lambda args, timeout=300.0: captured.setdefault("args", args) or "")
    ff.convert(str(tmp_path / "in.wav"), str(tmp_path / "o.mp3"), fmt="mp3", http_headers={"X": "y"})
    assert "-headers" not in captured["args"]


def test_duration_str_hours():
    t = Track.from_info({**VIDEO_INFO, "duration": 3725})
    assert t.duration_str == "1:02:05"


def test_search_returns_tracks():
    backend = FakeBackend(info={"entries": [VIDEO_INFO, VIDEO_INFO]})
    yt = YouTube(backend=backend)
    tracks = yt.search("rick", limit=2)
    assert len(tracks) == 2
    assert backend.extract_calls[0] == "ytsearch2:rick"


def test_search_one_empty():
    backend = FakeBackend(info={"entries": []})
    yt = YouTube(backend=backend)
    assert yt.search_one("nothing") is None


def test_search_handles_none_from_backend():
    """ignoreerrors can make yt-dlp return None; search must not crash."""
    backend = FakeBackend(info=None)
    yt = YouTube(backend=backend)
    assert yt.search("x") == []


def test_get_raises_on_none():
    from ytpush.errors import DownloadError

    backend = FakeBackend(info=None)
    yt = YouTube(backend=backend)
    with pytest.raises(DownloadError):
        yt.get("dQw4w9WgXcQ")


def test_get_raises_on_empty_playlist():
    from ytpush.errors import DownloadError

    backend = FakeBackend(info={"_type": "playlist", "entries": []})
    yt = YouTube(backend=backend)
    with pytest.raises(DownloadError):
        yt.get("some-playlist")


def test_get_and_stream_url():
    backend = FakeBackend()
    yt = YouTube(backend=backend)
    assert yt.get("dQw4w9WgXcQ").title.startswith("Rick")
    assert yt.stream_url("dQw4w9WgXcQ") == "https://audio-160"


def test_download_builds_postprocessor(tmp_path):
    backend = FakeBackend()
    yt = YouTube(backend=backend)
    path = yt.download("dQw4w9WgXcQ", out_dir=str(tmp_path), fmt="mp3", bitrate="192k")
    assert path.endswith("dQw4w9WgXcQ.mp3")
    call = backend.download_calls[0]
    assert call["format"] == "bestaudio/best"
    assert call["postprocessors"][0]["preferredcodec"] == "mp3"
    assert call["postprocessors"][0]["preferredquality"] == "192"
    assert call["target"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_download_custom_filename(tmp_path):
    backend = FakeBackend()
    yt = YouTube(backend=backend)
    yt.download("dQw4w9WgXcQ", out_dir=str(tmp_path), filename="cancao")
    assert "%(id)s" not in backend.download_calls[0]["outtmpl"]
    assert "cancao" in backend.download_calls[0]["outtmpl"]


def test_resolve_path_raises_when_no_file_written(tmp_path):
    """A 'successful' download that wrote nothing must raise, not lie."""
    from ytpush.backend import _resolve_path
    from ytpush.errors import DownloadError

    class FakeYdl:
        def prepare_filename(self, info):
            return str(tmp_path / "missing.mp3")

    with pytest.raises(DownloadError):
        _resolve_path(FakeYdl(), {"id": "x", "_filename": str(tmp_path / "missing.webm")})


def test_backend_options_include_cookies_and_client():
    from ytpush.backend import YtDlpBackend

    backend = YtDlpBackend(
        cookiefile="/tmp/cookies.txt",
        player_client="android",
    )
    opts = backend._base_opts()
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert opts["extractor_args"] == {"youtube": {"player_client": ["android"]}}
    assert opts["ignoreerrors"] is True


# -- ffmpeg --------------------------------------------------------------
def test_find_ffmpeg_reports_when_missing(monkeypatch):
    import ytpush.ffmpeg as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(mod, "_from_imageio", lambda: None)
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    with pytest.raises(mod.FFmpegNotFound):
        mod.find_ffmpeg()


def test_ffmpeg_run_raises_on_bad_binary():
    ff = FFmpeg.__new__(FFmpeg)
    ff.ffmpeg = "/nonexistent/ffmpeg"
    ff.ffprobe = None
    from ytpush.errors import FFmpegNotFound

    with pytest.raises(FFmpegNotFound):
        ff.run(["-version"])


def test_convert_end_to_end(tmp_path):
    """Really run ffmpeg: generate a tone, convert to mp3, read duration."""
    ff = FFmpeg()
    source = str(tmp_path / "tone.wav")
    ff.run([
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        source,
    ])
    assert os.path.exists(source)

    target = str(tmp_path / "tone.mp3")
    ff.convert(source, target, fmt="mp3", bitrate="128k")
    assert os.path.exists(target)
    assert os.path.getsize(target) > 0

    dur = ff.duration(target)
    assert dur is not None and 1.5 < dur < 2.5


def test_make_thumbnail(tmp_path):
    ff = FFmpeg()
    source = str(tmp_path / "clip.mp4")
    ff.run([
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=320x240:duration=2",
        "-pix_fmt", "yuv420p", source,
    ])
    out = str(tmp_path / "cover.jpg")
    ff.make_thumbnail(source, out, at=1.0, width=160)
    assert os.path.exists(out) and os.path.getsize(out) > 0


# -- fetcher -------------------------------------------------------------
def test_fetcher_search_then_download(tmp_path):
    from ytpush.fetcher import Fetcher

    backend = FakeBackend(info={"entries": [VIDEO_INFO]})
    yt = YouTube(backend=backend)
    fetcher = Fetcher(youtube=yt)
    # no stream conversion here because FakeBackend has no real ffmpeg path
    result = fetcher.fetch("rick", out_dir=str(tmp_path), with_cover=False, prefer_stream=False)
    assert result.video_id == "dQw4w9WgXcQ"
    assert result.audio_path.endswith(".mp3")
    assert backend.download_calls, "should have called the downloader"


def test_fetcher_sanitizes_filename(tmp_path):
    from ytpush.fetcher import Fetcher, _safe_name

    assert "/" not in _safe_name("AC/DC - Back in Black")
    backend = FakeBackend(info={"entries": [VIDEO_INFO]})
    fetcher = Fetcher(youtube=YouTube(backend=backend))
    result = fetcher.fetch("rick", out_dir=str(tmp_path), with_cover=False, prefer_stream=False)
    assert os.path.basename(result.audio_path).startswith("Rick_Astley")


def test_fetcher_raises_when_nothing_found(tmp_path):
    from ytpush.errors import DownloadError
    from ytpush.fetcher import Fetcher

    backend = FakeBackend(info={"entries": []})
    fetcher = Fetcher(youtube=YouTube(backend=backend))
    with pytest.raises(DownloadError):
        fetcher.fetch("nothing here", out_dir=str(tmp_path))
