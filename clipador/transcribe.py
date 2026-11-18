"""Transcrição com faster-whisper, com timestamps por palavra.

Transcreve só os intervalos pedidos (janelas candidatas) ou o vídeo inteiro.
Cada intervalo fica em cache separado, então uma queda no meio não perde o que
já foi feito.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from .cache import Workdir
from .download import SAMPLE_RATE

log = logging.getLogger("clipador")

_model = None


def has_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def _get_model(cfg: dict):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        t = cfg["transcribe"]
        device = t["device"]
        if device == "auto":
            device = "cuda" if has_cuda() else "cpu"
        compute = t["compute_type"]
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        log.info("Whisper: carregando modelo %s (%s, %s)", t["model"], device, compute)
        _model = WhisperModel(t["model"], device=device, compute_type=compute)
    return _model


def merge_intervals(intervals: list[tuple[float, float]], gap: float = 2.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _transcribe_range(model, audio: np.ndarray, start: float, end: float, cfg: dict) -> list[dict]:
    t = cfg["transcribe"]
    a = np.asarray(audio[int(start * SAMPLE_RATE): int(end * SAMPLE_RATE)], dtype=np.float32) / 32768.0
    segments, _ = model.transcribe(
        a, language=t["language"], word_timestamps=True, vad_filter=bool(t["vad_filter"]),
        condition_on_previous_text=False, beam_size=5,
    )
    out = []
    for seg in segments:
        words = [
            {"w": w.word.strip(), "s": round(start + w.start, 3), "e": round(start + w.end, 3),
             "p": round(w.probability, 3)}
            for w in (seg.words or []) if w.word.strip()
        ]
        if words:
            out.append({"s": words[0]["s"], "e": words[-1]["e"], "text": seg.text.strip(), "words": words})
    return out


def transcribe(audio: np.ndarray, intervals: list[tuple[float, float]], cfg: dict, wd: Workdir) -> list[dict]:
    """Transcreve os intervalos e devolve todos os segmentos, ordenados no tempo."""
    intervals = merge_intervals(intervals)
    total = sum(e - s for s, e in intervals)
    log.info("Transcrição: %d janela(s), %.1f min de áudio", len(intervals), total / 60)
    segs: list[dict] = []
    done = 0.0
    for s, e in intervals:
        name = f"transcript/{cfg['transcribe']['model']}_{s:.1f}_{e:.1f}.json"
        if wd.has(name):
            part = wd.load_json(name)
        else:
            t0 = time.time()
            part = _transcribe_range(_get_model(cfg), audio, s, e, cfg)
            wd.save_json(name, part)
            log.info("  %s–%s transcrito em %.0f s (%.1fx tempo real)",
                     fmt_time(s), fmt_time(e), time.time() - t0, (e - s) / max(time.time() - t0, 1e-6))
        segs.extend(part)
        done += e - s
        log.info("  transcrição: %3.0f%%", 100 * done / max(total, 1e-6))
    segs.sort(key=lambda x: x["s"])
    return segs


def words_in(segs: list[dict], start: float, end: float) -> list[dict]:
    return [w for seg in segs for w in seg["words"] if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]


def fmt_time(t: float) -> str:
    t = int(t)
    return f"{t // 3600:d}:{t % 3600 // 60:02d}:{t % 60:02d}"
