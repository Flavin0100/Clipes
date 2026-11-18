# Clipador

Passe o link de uma live (Twitch/YouTube) ou de um vídeo de gameplay e receba
cortes verticais 9:16 prontos para TikTok, Reels e Shorts — com legenda
palavra por palavra, facecam em cima, gameplay embaixo e relatório com
sugestões de título.

> **Status:** em construção. Fase 1 (MVP) em desenvolvimento. Veja o
> [plano](docs/PLANO.md).

## Uso (alvo)

```bash
clipador "https://www.twitch.tv/videos/123456789" --max-clips 10 --min 20 --max 60
clipador "https://youtu.be/XXXXXXXXXXX" --cookies-from-browser chrome
```

Saída em `output/<nome-do-video>/`: `clip_01.mp4`, `clip_02.mp4`, …,
`report.json` e `report.md`.

## Instalação

Requisitos: Python 3.11+, ffmpeg (com libass), git.

```bash
git clone https://github.com/flavin0100/clipes.git
cd clipes
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[vision,ai]"
cp .env.example .env               # coloque sua ANTHROPIC_API_KEY
```

### ffmpeg
- **Windows:** `winget install Gyan.FFmpeg`
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### GPU (opcional, NVIDIA)
O faster-whisper usa CUDA automaticamente se encontrar. Precisa de CUDA 12 +
cuDNN 9: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`. Sem GPU, roda em
CPU com `int8` (mais lento — veja o plano).

### Fonte
Baixe Montserrat Black e coloque em `assets/fonts/` (ver
`assets/fonts/README.md`).

## Estrutura

```
clipador/
  cli.py         linha de comando
  config.py      config.yaml + .env
  cache.py       cache por etapa (retomada)
  download.py    yt-dlp: áudio, chat, trechos de vídeo
  transcribe.py  faster-whisper
  detect.py      score de momentos (chat, áudio, Claude)
  layout.py      9:16, facecam, crop
  captions.py    legendas .ass karaokê
  render.py      ffmpeg final
config.yaml      pesos, estilo de legenda, layout
```
