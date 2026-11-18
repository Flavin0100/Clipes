# Clipador

Passe o link de uma live (Twitch/YouTube) ou de um vídeo de gameplay e receba
cortes verticais 9:16 prontos para TikTok, Reels e Shorts — com legenda
palavra por palavra, facecam em cima, gameplay embaixo e relatório com
sugestões de título.

> **Status:** Fase 1 (MVP) pronta: link → áudio + chat → picos → transcrição
> → top N → cortes 9:16 com legenda palavra por palavra. Facecam (Fase 2) e
> Claude/títulos (Fase 3) ainda não. Veja o [plano](docs/PLANO.md).

## Uso

```powershell
clipador "https://www.twitch.tv/videos/123456789"
clipador "https://www.twitch.tv/videos/123456789" --max-clips 10 --min 20 --max 60
clipador "https://youtu.be/XXXXXXXXXXX" --cookies-from-browser chrome
clipador "C:\Videos\minha_live.mp4"            # arquivo local também funciona
clipador <link> --layout blur_background        # vídeo inteiro com fundo desfocado
clipador <link> --model small                   # transcrição mais rápida, menos precisa
```

Se cair no meio (queda de internet, Ctrl+C), rode o mesmo comando de novo: cada
etapa fica em `cache/` e é retomada de onde parou.

### Como os momentos são escolhidos (MVP)
1. **Chat** (Twitch): mensagens por segundo e reações (KEKW, kkkk, MDS…) acima
   da média dos últimos minutos, compensando o atraso do chat (~8 s).
2. **Áudio**: volume acima do normal da vizinhança e subidas bruscas (gritos).
3. Os ~15 maiores picos são **transcritos** (em CPU, só essas janelas) e ganham
   pontos por palavras de reação ("caralho", "não acredito", "kkk"…).
4. Score 0–100, remove sobreposição, pega os top N e ajusta início/fim em
   limite de frase (com ~3 s de pré-roll, sem cortar palavra).

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
copy .env.example .env             # (Linux/macOS: cp) chave do Claude, opcional até a Fase 3
```

Configuração: copie `clipador/default_config.yaml` para `config.yaml` na pasta
onde você roda o comando e altere só o que quiser (pesos, legenda, durações).

### ffmpeg
- **Windows:** `winget install Gyan.FFmpeg`
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### GPU (opcional, NVIDIA)
O faster-whisper usa CUDA automaticamente se encontrar. Precisa de CUDA 12 +
cuDNN 9: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`. Sem GPU, roda em
CPU com `int8` (mais lento — veja o plano).

### Fonte
Baixe `Montserrat-Black.ttf` e coloque em `assets/fonts/`:

```powershell
curl.exe -L -o assets/fonts/Montserrat-Black.ttf https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf
```

### Desempenho em CPU (sem GPU)
O modelo padrão é `large-v3-turbo` em `int8`. Numa live longa, só ~15 janelas
de ~2 min são transcritas. Se ficar lento, use `--model small`.

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
  report.py      report.json / report.md
  pipeline.py    orquestração das etapas
  default_config.yaml   pesos, estilo de legenda, layout
```
