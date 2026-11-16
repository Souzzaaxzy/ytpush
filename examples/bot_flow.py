"""Example bot flow: search a song, download the audio and the cover.

    python examples/bot_flow.py "daft punk instant crush"

Produces an mp3 and a cover image ready to send to a chat, then shows the
ffmpeg command the bot would run.
"""

import os
import sys

from ytpush import Fetcher

query = " ".join(sys.argv[1:]) or "daft punk instant crush"
out_dir = "downloads"

fetcher = Fetcher()
result = fetcher.fetch(query, out_dir=out_dir, fmt="mp3", bitrate="192k")

print("=" * 60)
print("Título   :", result.title)
print("Artista  :", result.artist)
print("Duração  :", result.duration, "s")
print("Áudio    :", result.audio_path, f"({os.path.getsize(result.audio_path)} bytes)")
print("Capa     :", result.cover_path)
print("Fonte    :", result.source_url)
print("=" * 60)
print("\nAgora é só mandar o arquivo pro chat:")
print(f"  arquivo de áudio -> {result.audio_path}")
print(f"  capa             -> {result.cover_path}")
