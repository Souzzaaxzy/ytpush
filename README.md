# ytpush

Sua própria ferramenta de **busca e download de áudio do YouTube**, feita em
cima do [yt-dlp](https://github.com/yt-dlp/yt-dlp) + **ffmpeg**. Pega metadados,
URL do áudio, thumbnail, capa, e gera o arquivo pronto pra mandar num chat.

Pensada pro caso "bot pega a música e manda o arquivo".

```python
from ytpush import YouTube, Fetcher

yt = YouTube()

# buscar
track = yt.search_one("daft punk instant crush")
print(track.title, track.duration_str, track.thumbnail)

# URL direta do áudio (googlevideo) — dá pra jogar direto no ffmpeg
print(track.audio_url)

# baixar: áudio + capa
path = yt.download(track.id, out_dir="downloads", fmt="mp3", bitrate="192k")
cover = yt.download_cover(track.id, out_dir="downloads")
```

Ou tudo de uma vez, que é o que um bot costuma querer:

```python
from ytpush import Fetcher

fetcher = Fetcher()
result = fetcher.fetch("daft punk instant crush", out_dir="downloads", fmt="mp3")
print(result.title, result.artist, result.duration)
print(result.audio_path)   # downloads/Daft_Punk_-_....mp3
print(result.cover_path)   # downloads/<id>.webp
```

## Requisito importante: runtime JavaScript

O YouTube agora esconde as URLs de áudio atrás de um **desafio JavaScript**.
Sem resolvê-lo, o yt-dlp só enxerga imagens (storyboards) e o download falha.
A lib resolve isso automaticamente, mas você precisa ter:

1. **Um runtime JS instalado** — `node`, `deno` ou `bun` (a lib detecta sozinha);
2. **O pacote `yt-dlp-ejs`** — já vem como dependência (`pip install -e .`).

Se aparecer no log `Signature solving failed` ou `Only images are available`,
é isso que falta. Verifique com:

```bash
python -c "from ytpush.backend import _default_js_runtimes; print(_default_js_runtimes())"
# {'node': {'path': '/usr/bin/node'}}   <- ok
# None                                   <- instale node/deno/bun
```

## Instalação

```bash
pip install -e ".[ffmpeg]"     # yt-dlp + yt-dlp-ejs + ffmpeg estático
```

Se já tem ffmpeg no sistema, `pip install -e .` basta (o runtime JS ainda é
necessário).

O ffmpeg é procurado, nesta ordem:

1. o argumento `ffmpeg_location` / `FFMPEG_BINARY`
2. `ffmpeg` no `PATH`
3. o binário do **imageio-ffmpeg** (estático, instalável por pip, sem root)

## O que dá pra pegar

| Campo | Onde |
|---|---|
| Título, artista/canal, duração | `Track` |
| Thumbnail (URL) + todas as resoluções | `Track.thumbnail`, `Track.thumbnails` |
| URL direta do áudio (stream) | `Track.audio_url` |
| Formato e bitrate do áudio | `Track.audio_format`, `Track.audio_bitrate` |
| Licença (quando informada) | `Track.license` |
| Embed / watch URL | `Track.embed_url`, `Track.watch_url` |
| Arquivo de áudio convertido | `YouTube.download()` |
| Imagem de capa | `YouTube.download_cover()` |

## Fluxos

### Só metadados (sem baixar)

```python
yt = YouTube()
tracks = yt.search("lofi hip hop", limit=5)
url = yt.stream_url("dQw4w9WgXcQ")   # URL do áudio
```

### Áudio direto da URL (sem arquivo intermediário)

```python
from ytpush import YouTube, FFmpeg

yt = YouTube()
track = yt.get("dQw4w9WgXcQ")
FFmpeg().convert(track.audio_url, "saida.mp3", fmt="mp3", bitrate="128k")
```

### Converter / cortar / normalizar

```python
from ytpush import FFmpeg

ff = FFmpeg()
ff.convert("entrada.webm", "saida.mp3", fmt="mp3", bitrate="192k")
ff.convert("saida.mp3", "trecho.mp3", start=30, duration=15)      # corta 15s a partir de 0:30
ff.convert("saida.mp3", "norm.mp3", normalize=True)                # loudness -16 LUFS
print(ff.duration("saida.mp3"))
```

## Cookies e bloqueio "not a bot"

De um IP de datacenter (VPS, CI, container) o YouTube pode devolver **403** no
stream. Isso é detecção anti-bot do YouTube, não um bug da lib. Cookies de uma
conta logada resolvem:

```python
yt = YouTube(cookiefile="/caminho/cookies.txt")        # arquivo Netscape (yt-dlp)
yt = YouTube(cookies_from_browser="chrome")             # direto do navegador
yt = YouTube(player_client="android")                   # troca o player client
```

O arquivo de cookies pode ser exportado com a extensão "Get cookies.txt" ou com
`yt-dlp --cookies-from-browser chrome --cookies cookies.txt`.

> ⚠️ Cookie de conta = acesso à conta. Use uma conta descartável e proteja o
> arquivo (`chmod 600`).

A lib manda os headers do YouTube **e** o cookie quando o ffmpeg lê o stream
direto, e usa o mesmo cookie no downloader do yt-dlp.

## Aviso de uso

Baixe apenas conteúdo que **você tem direito** de baixar: seus próprios vídeos,
material com licença Creative Commons ou de domínio público. Respeite os
[Termos de Serviço do YouTube](https://www.youtube.com/t/terms) e o direito
autoral. O yt-dlp é software livre; o uso é responsabilidade sua.

## Estrutura

```
ytpush/
  client.py     YouTube: search, get, stream_url, download, download_cover
  fetcher.py    Fetcher: busca -> baixa áudio + capa (pronto pro bot)
  backend.py    YtDlpBackend: wrapper do yt-dlp (injetável p/ testes)
  ffmpeg.py     FFmpeg: localiza o binário, converte, corta, normaliza, capa
  models.py     Track / Thumbnail
  errors.py     hierarquia de exceções
```

## Testes

```bash
pytest
```

Os testes de rede usam um backend falso; os de ffmpeg geram áudio de verdade
com o próprio ffmpeg e conferem duração e tamanho.

## Licença

MIT.
