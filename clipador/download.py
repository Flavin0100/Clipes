"""Download inteligente.

1. ``probe``: metadados (título, duração, fps) sem baixar nada.
2. ``download_audio``: só o áudio, convertido para PCM 16 kHz mono (análise + Whisper).
3. ``download_chat``: replay do chat (Twitch via GQL, YouTube via yt-dlp live_chat).
4. ``download_section``: vídeo em alta só do trecho escolhido. O alinhamento exato
   do trecho com o original é feito por correlação de áudio (veja ``align``).

Também aceita arquivo local no lugar do link (útil para testes e para VODs já baixados).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .cache import Workdir

log = logging.getLogger("clipador")

SAMPLE_RATE = 16000
TWITCH_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
TWITCH_COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


@dataclass
class Source:
    url: str
    id: str
    title: str
    duration: float
    extractor: str          # twitch / youtube / local / outro
    fps: float = 30.0
    local_path: str | None = None

    @property
    def is_local(self) -> bool:
        return self.local_path is not None

    def link_at(self, t: float) -> str:
        t = int(t)
        if self.extractor == "twitch":
            h, m, s = t // 3600, t % 3600 // 60, t % 60
            return f"{self.url}?t={h}h{m}m{s}s"
        if self.extractor == "youtube":
            return f"https://www.youtube.com/watch?v={self.id}&t={t}s"
        return f"{self.url} @ {t}s"


# --------------------------------------------------------------------------- ffmpeg

def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(
                f"{tool} não encontrado no PATH. Instale o ffmpeg "
                "(Windows: winget install Gyan.FFmpeg) e abra um terminal novo."
            )


def proxy_args() -> list[str]:
    """Proxy HTTP(S) do ambiente para o ffmpeg (ele não lê HTTPS_PROXY sozinho)."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY")
    return ["-http_proxy", proxy] if proxy else []


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log.debug("$ %s", " ".join(map(str, cmd)))
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if res.returncode != 0:
        raise RuntimeError(f"Comando falhou ({res.returncode}): {cmd[0]}\n{res.stderr[-2000:]}")
    return res


def ffprobe_json(path: str | Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(out.stdout)


def _fps_of(probe: dict) -> float:
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video":
            num, _, den = s.get("avg_frame_rate", "30/1").partition("/")
            try:
                return float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                return 30.0
    return 30.0


def to_pcm(src: str | Path, dst: Path, start: float | None = None, dur: float | None = None) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    tmp = dst.with_suffix(".tmp")
    cmd += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", str(tmp)]
    run(cmd)
    tmp.replace(dst)
    return dst


def load_pcm(path: Path) -> np.ndarray:
    """Áudio PCM s16le como memmap (não carrega a live inteira na memória)."""
    return np.memmap(path, dtype=np.int16, mode="r")


# --------------------------------------------------------------------------- yt-dlp

def _ydl_opts(cfg: dict, **extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True}
    browser = cfg["download"].get("cookies_from_browser")
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    if proxy_args():
        opts["external_downloader_args"] = {"ffmpeg_i": proxy_args()}
    opts.update(extra)
    return opts


def probe(url: str, cfg: dict) -> Source:
    p = Path(url)
    if p.exists():
        info = ffprobe_json(p)
        return Source(
            url=str(p.resolve()), id=p.stem, title=p.stem,
            duration=float(info["format"]["duration"]), extractor="local",
            fps=_fps_of(info), local_path=str(p.resolve()),
        )
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_opts(cfg)) as ydl:
        info = ydl.extract_info(url, download=False)
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    if "twitch" in extractor:
        extractor = "twitch"
    elif "youtube" in extractor:
        extractor = "youtube"
    vid = str(info.get("id", "video")).lstrip("v") if extractor == "twitch" else str(info.get("id"))
    return Source(
        url=info.get("webpage_url") or url, id=vid,
        title=info.get("title") or vid, duration=float(info.get("duration") or 0),
        extractor=extractor or "outro", fps=float(info.get("fps") or 30),
    )


class _Progress:
    def __init__(self, label: str):
        self.label, self.last = label, -10.0

    def __call__(self, d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d.get("fragment_count"):
            pct = 100.0 * (d.get("fragment_index") or 0) / d["fragment_count"]
        elif total:
            pct = 100.0 * d.get("downloaded_bytes", 0) / total
        else:
            return
        if pct - self.last >= 10:
            self.last = pct
            log.info("  %s: %3.0f%%", self.label, pct)


def download_audio(src: Source, cfg: dict, wd: Workdir) -> Path:
    pcm = wd.path("audio.pcm")
    if wd.has("audio.pcm"):
        log.info("Áudio: usando cache")
        return pcm
    if src.is_local:
        log.info("Áudio: extraindo do arquivo local")
        return to_pcm(src.local_path, pcm)

    import yt_dlp

    log.info("Áudio: baixando só a faixa de áudio (leve)")
    outtmpl = str(wd.dir / "audio_src.%(ext)s")
    opts = _ydl_opts(
        cfg, format="Audio_Only/bestaudio/best[height<=360]/best", outtmpl=outtmpl,
        progress_hooks=[_Progress("áudio")], concurrent_fragment_downloads=8,
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(src.url, download=True)
        fname = ydl.prepare_filename(info)
    log.info("Áudio: convertendo para 16 kHz mono")
    to_pcm(fname, pcm)
    Path(fname).unlink(missing_ok=True)
    return pcm


# --------------------------------------------------------------------------- chat

def _twitch_gql(body: list) -> list:
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps(body).encode(),
        headers={"Client-ID": TWITCH_CLIENT_ID, "Content-Type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - rede instável: tenta de novo
            if attempt == 4:
                raise
            log.debug("GQL falhou (%s), tentando de novo", e)
            time.sleep(1.5 * (attempt + 1))
    return []


def _twitch_chat_range(video_id: str, t0: float, t1: float, progress) -> dict[str, list]:
    """Mensagens com offset em [t0, t1). Paginação por cursor a partir de t0."""
    msgs: dict[str, list] = {}
    cursor = None
    while True:
        variables: dict = {"videoID": video_id}
        if cursor:
            variables["cursor"] = cursor
        else:
            variables["contentOffsetSeconds"] = int(t0)
        data = _twitch_gql([{
            "operationName": "VideoCommentsByOffsetOrCursor", "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TWITCH_COMMENTS_HASH}},
        }])
        video = (data[0].get("data") or {}).get("video") if data else None
        comments = (video or {}).get("comments")
        if not comments or not comments["edges"]:
            break
        last = t0
        for edge in comments["edges"]:
            node = edge["node"]
            last = float(node["contentOffsetSeconds"])
            if t0 <= last < t1:
                text = "".join(f.get("text", "") for f in (node.get("message") or {}).get("fragments") or [])
                msgs[node["id"]] = [last, text]
        progress(len(comments["edges"]), last)
        if last >= t1 or not comments["pageInfo"].get("hasNextPage"):
            break
        cursor = comments["edges"][-1]["cursor"]
    return msgs


def _twitch_chat(video_id: str, duration: float, workers: int = 8) -> list[list]:
    """Baixa o chat em blocos de tempo paralelos (lives longas ficam ~8x mais rápidas)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    duration = max(duration, 1.0)
    n = max(1, min(workers, int(duration // 600) or 1))
    edges = [duration * i / n for i in range(n + 1)]
    edges[-1] = float("inf")
    lock = threading.Lock()
    state = {"msgs": 0, "covered": [0.0] * n, "last_pct": -10.0}

    def make_progress(i: int):
        def progress(count: int, last: float) -> None:
            with lock:
                state["msgs"] += count
                state["covered"][i] = min(last, edges[i + 1]) - edges[i]
                pct = 100 * sum(state["covered"]) / duration
                if pct - state["last_pct"] >= 10:
                    state["last_pct"] = pct
                    log.info("  chat: %3.0f%% (%d mensagens)", min(pct, 100), state["msgs"])
        return progress

    with ThreadPoolExecutor(n) as ex:
        parts = list(ex.map(lambda i: _twitch_chat_range(video_id, edges[i], edges[i + 1], make_progress(i)),
                            range(n)))
    merged: dict[str, list] = {}
    for p in parts:
        merged.update(p)
    return sorted(merged.values(), key=lambda m: m[0])


def _youtube_chat(src: Source, cfg: dict, wd: Workdir) -> list[list]:
    import yt_dlp

    opts = _ydl_opts(
        cfg, skip_download=True, writesubtitles=True, subtitleslangs=["live_chat"],
        outtmpl=str(wd.dir / "yt_chat.%(ext)s"),
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([src.url])
    f = wd.dir / "yt_chat.live_chat.json"
    msgs: list[list] = []
    if not f.exists():
        return msgs
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)["replayChatItemAction"]
                t = float(d["videoOffsetTimeMsec"]) / 1000
                for act in d["actions"]:
                    item = act.get("addChatItemAction", {}).get("item", {})
                    r = item.get("liveChatTextMessageRenderer")
                    if not r:
                        continue
                    parts = []
                    for run_ in r.get("message", {}).get("runs", []):
                        if "text" in run_:
                            parts.append(run_["text"])
                        elif "emoji" in run_:
                            parts.append((run_["emoji"].get("shortcuts") or [""])[0])
                    msgs.append([t, "".join(parts)])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return msgs


def download_chat(src: Source, cfg: dict, wd: Workdir) -> list[list] | None:
    """Retorna lista de [segundos, texto] ou None se não houver chat."""
    if wd.has("chat.json"):
        log.info("Chat: usando cache")
        msgs = wd.load_json("chat.json")
        return msgs or None
    msgs: list[list] = []
    try:
        if src.extractor == "twitch":
            log.info("Chat: baixando replay da Twitch")
            msgs = _twitch_chat(src.id, src.duration)
        elif src.extractor == "youtube":
            log.info("Chat: baixando replay do YouTube (live_chat)")
            msgs = _youtube_chat(src, cfg, wd)
    except Exception as e:  # noqa: BLE001
        log.warning("Chat: falhou (%s). Seguindo só com áudio + transcrição.", e)
        return None
    wd.save_json("chat.json", msgs)
    if not msgs:
        log.warning("Chat: nenhum replay de chat encontrado. Seguindo só com áudio + transcrição.")
        return None
    log.info("Chat: %d mensagens", len(msgs))
    return msgs


# --------------------------------------------------------------------------- trechos de vídeo

def _stream_inputs(src: Source, cfg: dict) -> tuple[list[str], dict]:
    """URLs diretas (vídeo [+ áudio]) para o ffmpeg ler só o trecho."""
    import yt_dlp

    h = int(cfg["download"]["clip_video_height"])
    fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    with yt_dlp.YoutubeDL(_ydl_opts(cfg, format=fmt)) as ydl:
        info = ydl.extract_info(src.url, download=False)
    fmts = info.get("requested_formats") or [info]
    headers = fmts[0].get("http_headers") or {}
    return [f["url"] for f in fmts], headers


def align(section_audio: np.ndarray, full_audio: np.ndarray, guess: float, search: float = 15.0) -> float:
    """Acha onde o trecho começa no áudio original (em segundos) por correlação cruzada.

    Usa áudio decimado para 2 kHz (rápido) e refina em 16 kHz.
    """
    sr = SAMPLE_RATE
    probe_len = min(len(section_audio), 12 * sr)
    a = section_audio[:probe_len].astype(np.float32)
    lo = max(0, int((guess - search) * sr))
    hi = min(len(full_audio), int((guess + search) * sr) + probe_len)
    b = np.asarray(full_audio[lo:hi], dtype=np.float32)
    if len(b) < probe_len or not np.any(a):
        return guess

    def xcorr(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        n = len(x) + len(y)
        nfft = 1 << (n - 1).bit_length()
        r = np.fft.irfft(np.fft.rfft(y, nfft) * np.conj(np.fft.rfft(x, nfft)), nfft)
        return r[: len(y) - len(x) + 1]

    k = 8
    coarse = xcorr(a[::k], b[::k])
    best = int(np.argmax(coarse)) * k
    w0 = max(0, best - 4 * k)
    fine = xcorr(a, b[w0: w0 + probe_len + 8 * k])
    best = w0 + int(np.argmax(fine))
    return (lo + best) / sr


def _http_get(url: str, headers: dict, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
    return b""


def _hls_section(url: str, headers: dict, s0: float, s1: float, out: Path) -> float | None:
    """Baixa só os segmentos HLS que cobrem [s0, s1] e concatena.

    Retorna o tempo (no original) do início do primeiro segmento, ou None se a
    playlist não for HLS simples (aí cai no método via ffmpeg).
    """
    from urllib.parse import urljoin

    text = _http_get(url, headers).decode("utf-8", "replace")
    if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" in text or "#EXT-X-BYTERANGE" in text \
            or "#EXT-X-KEY" in text:
        return None
    init_uri, t, dur = None, 0.0, None
    segs: list[tuple[float, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MAP:"):
            init_uri = line.split('URI="', 1)[1].split('"', 1)[0]
        elif line.startswith("#EXTINF:"):
            dur = float(line[8:].split(",", 1)[0])
        elif line and not line.startswith("#") and dur is not None:
            segs.append((t, line))
            t += dur
            dur = None
    chosen = [(st, u) for i, (st, u) in enumerate(segs)
              if st < s1 and (segs[i + 1][0] if i + 1 < len(segs) else t) > s0]
    if not chosen:
        return None
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(6) as ex:
        blobs = list(ex.map(lambda u: _http_get(urljoin(url, u), headers), [u for _, u in chosen]))
    tmp = out.with_suffix(".part")
    with tmp.open("wb") as f:
        if init_uri:
            f.write(_http_get(urljoin(url, init_uri), headers))
        for b in blobs:
            f.write(b)
    # Remux para um MP4 normal (timestamps a partir de 0).
    ext = ".mp4" if init_uri else ".ts"
    raw = tmp.with_suffix(ext + ".raw")
    tmp.replace(raw)
    run(["ffmpeg", "-y", "-v", "error", "-f", "mp4" if init_uri else "mpegts", "-i", str(raw),
         "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)])
    raw.unlink(missing_ok=True)
    return chosen[0][0]


def download_section(src: Source, cfg: dict, wd: Workdir, name: str, start: float, end: float,
                     full_audio: np.ndarray) -> tuple[Path, float]:
    """Baixa o trecho [start, end] (+ margem). Retorna (arquivo, tempo original do t=0 do arquivo)."""
    if src.is_local:
        return Path(src.local_path), 0.0
    out = wd.path(f"sections/{name}.mp4")
    meta_name = f"sections/{name}.json"
    if wd.has(f"sections/{name}.mp4") and wd.has(meta_name):
        meta = wd.load_json(meta_name)
        if meta["start"] <= start and meta["end"] >= end:
            return out, meta["offset"]

    pad = float(cfg["download"]["section_padding_seconds"])
    s0 = max(0.0, start - pad)
    dur = end - start + 2 * pad
    urls, headers = _stream_inputs(src, cfg)

    guess = None
    if len(urls) == 1 and ".m3u8" in urls[0]:
        guess = _hls_section(urls[0], headers, s0, s0 + dur, out)
    if guess is None:
        cmd = ["ffmpeg", "-y", "-v", "error"]
        hdr = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        for u in urls:
            if hdr:
                cmd += ["-headers", hdr]
            cmd += proxy_args() + ["-ss", f"{s0:.3f}", "-i", u]
        for i in range(len(urls)):
            cmd += ["-map", f"{i}"]
        tmp = out.with_suffix(".part.mp4")
        cmd += ["-t", f"{dur:.3f}", "-c", "copy", str(tmp)]
        run(cmd)
        tmp.replace(out)
        guess = s0

    # Confere/refina o deslocamento comparando o áudio do trecho com o áudio
    # completo (com -c copy o início real cai num keyframe, não no segundo pedido).
    offset = guess
    try:
        sec_pcm = to_pcm(out, wd.path(f"sections/{name}.pcm"), dur=14)
        found = align(load_pcm(sec_pcm), full_audio, guess=guess)
        sec_pcm.unlink(missing_ok=True)
        if abs(found - guess) < 12:
            offset = found
    except RuntimeError as e:  # trecho sem áudio
        log.debug("alinhamento por áudio falhou: %s", e)
    wd.save_json(meta_name, {"start": start, "end": end, "offset": offset})
    log.debug("trecho %s: segmento em %.2f, alinhado em %.2f", name, guess, offset)
    return out, offset


def source_dict(src: Source) -> dict:
    return asdict(src)
