"""Orquestra as etapas: download → sinais → transcrição → detecção → render → relatório."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import captions, detect, download, render, report, transcribe
from .cache import Workdir, safe_name
from .config import has_anthropic_key

log = logging.getLogger("clipador")


def run_pipeline(url: str, cfg: dict) -> Path:
    t0 = time.time()
    download.require_ffmpeg()
    notes: list[str] = []
    c = cfg["clips"]

    log.info("[1/6] Lendo informações do vídeo")
    src = download.probe(url, cfg)
    log.info("  %s (%s, %s)", src.title, src.extractor, transcribe.fmt_time(src.duration))
    wd = Workdir(cfg["paths"]["cache_dir"], f"{src.extractor}_{src.id}")
    wd.save_json("source.json", download.source_dict(src))

    log.info("[2/6] Baixando áudio e chat")
    pcm = download.download_audio(src, cfg, wd)
    audio = download.load_pcm(pcm)
    total = len(audio) / download.SAMPLE_RATE
    msgs = download.download_chat(src, cfg, wd)
    if not msgs:
        notes.append("Sem chat: score calculado só com áudio e transcrição.")

    log.info("[3/6] Procurando picos de chat e áudio")
    sig = detect.build_signals(audio, msgs, cfg)
    k = int(cfg["detect"]["candidates"])
    peaks = detect.find_peaks(sig.combined, k, sep=int(c["max_seconds"]) // 2,
                             edge=int(cfg["detect"]["ignore_edges_seconds"]))
    log.info("  %d candidatos: %s", len(peaks), ", ".join(transcribe.fmt_time(p) for p in sorted(peaks)))

    log.info("[4/6] Transcrevendo")
    gpu = transcribe.has_cuda() and cfg["transcribe"]["device"] != "cpu"
    full = gpu or total / 60 <= float(cfg["transcribe"]["full_transcript_max_minutes_cpu"])
    if full:
        intervals = [(0.0, total)]
    else:
        mx = float(c["max_seconds"])
        intervals = [(max(0.0, p - mx - 5), min(total, p + mx)) for p in peaks]
        log.info("  CPU + vídeo longo: transcrevendo só as janelas candidatas")
    segs = transcribe.transcribe(audio, intervals, cfg, wd)

    log.info("[5/6] Pontuando momentos")
    if cfg["detect"]["semantic"]["enabled"] in (True, "auto") and has_anthropic_key():
        notes.append("Análise com Claude ainda não implementada (Fase 3); usando heurísticas de texto.")
    moments = detect.score_moments(peaks, sig, segs, cfg, total)
    chosen = detect.select(moments, int(c["max_clips"]), float(c["min_gap_seconds"]))
    for i, m in enumerate(chosen, 1):
        log.info("  #%d %s–%s score %.0f | %s", i, transcribe.fmt_time(m.start), transcribe.fmt_time(m.end),
                 m.score, "; ".join(m.reasons) or "-")
    wd.save_json("moments.json", [m.__dict__ for m in moments])

    log.info("[6/6] Gerando os cortes")
    out_dir = Path(cfg["paths"]["output_dir"]) / safe_name(src.title)
    out_dir.mkdir(parents=True, exist_ok=True)
    done: list[tuple[str, detect.Moment]] = []
    for i, m in enumerate(chosen, 1):
        name = f"clip_{i:02d}.mp4"
        log.info("  %s: baixando trecho %s–%s", name, transcribe.fmt_time(m.start), transcribe.fmt_time(m.end))
        sec, off = download.download_section(src, cfg, wd, f"{int(m.start)}_{int(m.end)}", m.start, m.end, audio)
        work = wd.path(f"render/{i:02d}/x").parent
        words = transcribe.words_in(segs, m.start, m.end)
        ass = captions.build_ass(words, m.start, m.end, cfg, work / "clip.ass")
        log.info("  %s: renderizando", name)
        render.render_clip(sec, off, m.start, m.end, ass, out_dir / name, src.fps, cfg)
        done.append((name, m))

    report.write_reports(out_dir, src, done, notes)
    log.info("Pronto em %.0f s: %d corte(s) em %s", time.time() - t0, len(done), out_dir)
    return out_dir
