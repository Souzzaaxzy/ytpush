"""The yt-dlp backend.

Kept behind a tiny interface so the client can be tested without the network:
:class:`YtDlpBackend` is the real one, and tests pass a fake with the same two
methods (``extract`` and ``download``).
"""

from __future__ import annotations

import os
import shutil
from typing import List, Optional, Sequence

from .errors import DownloadError


def _detect_ffmpeg_location() -> Optional[str]:
    """Find ffmpeg so yt-dlp can post-process, without importing ffmpeg.py."""
    path = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if path and os.path.exists(path):
        return path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def _default_js_runtimes() -> Optional[dict]:
    """Detect an available JS runtime for yt-dlp's challenge solver.

    YouTube's audio URLs are gated behind a JS challenge; yt-dlp solves it with
    a runtime plus the ``yt-dlp-ejs`` package. Without one, only storyboard
    images are exposed as formats.
    """
    for name, binary in (("node", "node"), ("deno", "deno"), ("bun", "bun")):
        path = shutil.which(binary)
        if path:
            return {name: {"path": path}}
    return None


class YtDlpBackend:
    """Wraps :mod:`yt_dlp`."""

    def __init__(
        self,
        *,
        ffmpeg_location: Optional[str] = None,
        quiet: bool = True,
        cookiefile: Optional[str] = None,
        cookies_from_browser: Optional[str] = None,
        player_client: Optional[str] = None,
        js_runtimes: Optional[dict] = None,
        remote_components: Optional[Sequence[str]] = None,
    ) -> None:
        self.ffmpeg_location = ffmpeg_location or _detect_ffmpeg_location()
        self.quiet = quiet
        self.cookiefile = cookiefile
        self.cookies_from_browser = cookies_from_browser
        self.player_client = player_client
        # YouTube now gates audio formats behind a JavaScript challenge. yt-dlp
        # needs a JS runtime (node/deno) plus the yt-dlp-ejs solver, or the only
        # formats it sees are storyboard images.
        self.js_runtimes = js_runtimes if js_runtimes is not None else _default_js_runtimes()
        self.remote_components = remote_components

    def _base_opts(self) -> dict:
        opts = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": True,
            "skip_download": True,
            "nocheckcertificate": True,
            "extract_flat": False,
            # A search result often contains videos that are unavailable in the
            # caller's region or taken down. Skip those instead of failing the
            # whole batch.
            "ignoreerrors": True,
        }
        if self.ffmpeg_location:
            opts["ffmpeg_location"] = self.ffmpeg_location
        if self.cookiefile:
            opts["cookiefile"] = self.cookiefile
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        if self.player_client:
            opts["extractor_args"] = {"youtube": {"player_client": [self.player_client]}}
        if self.js_runtimes:
            opts["js_runtimes"] = self.js_runtimes
        if self.remote_components:
            opts["remote_components"] = list(self.remote_components)
        return opts

    def extract(self, target: str) -> dict:
        """Return the info dict for a URL, id or ``ytsearchN:query``.

        Unavailable entries inside a search are dropped, so the caller gets the
        results that actually work.
        """
        import yt_dlp

        with yt_dlp.YoutubeDL(self._base_opts()) as ydl:
            try:
                info = ydl.extract_info(target, download=False)
            except Exception as exc:  # noqa: BLE001 - normalise yt-dlp errors
                raise DownloadError(f"extraction failed for {target!r}: {exc}") from exc
        if info and info.get("_type") == "playlist":
            info = dict(info)
            info["entries"] = [e for e in (info.get("entries") or []) if e]
        return info

    def download(
        self,
        target: str,
        *,
        outtmpl: str,
        format_selector: str = "bestaudio/best",
        postprocessors: Optional[Sequence[dict]] = None,
        extra_opts: Optional[dict] = None,
    ) -> str:
        """Download ``target`` and return the resulting file path."""
        import yt_dlp

        opts = self._base_opts()
        opts.update(
            {
                "skip_download": False,
                "outtmpl": outtmpl,
                "format": format_selector,
                "postprocessors": list(postprocessors or []),
            }
        )
        if extra_opts:
            opts.update(extra_opts)

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(target, download=True)
            except Exception as exc:  # noqa: BLE001
                raise DownloadError(f"download failed for {target!r}: {exc}") from exc
        return _resolve_path(ydl, info)


def _resolve_path(ydl, info: dict) -> str:
    """Find the file yt-dlp actually wrote, or raise if nothing was written."""
    candidates = []
    requested = info.get("requested_downloads")
    if requested and requested[0].get("filepath"):
        candidates.append(requested[0]["filepath"])
    if info.get("_filename"):
        candidates.append(info["_filename"])
    try:
        prepared = ydl.prepare_filename(info)
    except Exception:  # noqa: BLE001
        prepared = None
    if prepared:
        candidates.append(prepared)
        base, _ = os.path.splitext(prepared)
        candidates += [base + ext for ext in (".mp3", ".m4a", ".opus", ".webm", ".wav", ".ogg")]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    raise DownloadError(
        "yt-dlp reported success but no output file was found; the download was "
        "likely blocked (e.g. 'Sign in to confirm you're not a bot'). Try passing "
        "cookies via extra_opts, or run from a non-datacenter network."
    )
