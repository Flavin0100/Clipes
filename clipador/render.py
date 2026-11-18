"""Render final: layout 9:16 + legenda (libass) + áudio normalizado (loudnorm 2 passadas)."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from .config import resolve_asset
from .download import run
from .layout import video_filter

log = logging.getLogger("clipador")


def measure_loudness(src: Path, ss: float, dur: float, cfg: dict) -> dict | None:
    r = cfg["render"]
    res = run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{ss:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
        "-vn", "-af", f"loudnorm=I={r['audio_lufs']}:TP={r['audio_true_peak']}:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr, re.S)
    return json.loads(m.group(0)) if m else None


def render_clip(section: Path, section_offset: float, start: float, end: float, ass: Path,
                out: Path, src_fps: float, cfg: dict) -> Path:
    r = cfg["render"]
    ss = max(0.0, start - section_offset)
    dur = end - start
    work = ass.parent

    # A legenda e a fonte ficam na pasta de trabalho e são referenciadas por
    # caminho relativo: evita o problema de escapar "C:\..." no filtro do ffmpeg.
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    font_file = resolve_asset(cfg["captions"]["font_file"])
    if font_file.exists():
        shutil.copy2(font_file, fonts / font_file.name)
    else:
        log.warning("Fonte %s não encontrada; o libass vai usar uma fonte do sistema.", font_file)

    vf = video_filter(cfg) + f";[v]subtitles={ass.name}:fontsdir=fonts[vout]"

    m = measure_loudness(section, ss, dur, cfg)
    target = f"I={r['audio_lufs']}:TP={r['audio_true_peak']}:LRA=11"
    if m and m.get("input_i") not in (None, "-inf"):
        af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true")
    else:
        af = f"loudnorm={target}"
    af += ",aresample=48000"

    fps = cfg["layout"]["fps"]
    fps = min(60, round(src_fps)) if fps == "auto" else int(fps)
    fade_out = max(0.0, dur - 0.15)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-v", "error",
        "-ss", f"{ss:.3f}", "-i", str(section.resolve()), "-t", f"{dur:.3f}",
        "-filter_complex", vf, "-map", "[vout]", "-map", "0:a:0?",
        "-af", af + f",afade=t=in:d=0.08,afade=t=out:st={fade_out:.2f}:d=0.15",
        "-r", str(fps), "-c:v", r["video_codec"], "-preset", r["preset"], "-crf", str(r["crf"]),
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(out.resolve()),
    ]
    run(cmd, cwd=work)
    return out
