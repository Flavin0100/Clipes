"""report.json + report.md com os cortes gerados."""

from __future__ import annotations

from pathlib import Path

from .cache import Workdir
from .detect import Moment
from .download import Source, source_dict
from .transcribe import fmt_time


def write_reports(out_dir: Path, src: Source, clips: list[tuple[str, Moment]], notes: list[str]) -> None:
    data = {
        "source": source_dict(src),
        "notes": notes,
        "clips": [
            {
                "file": name,
                "start": round(m.start, 2),
                "end": round(m.end, 2),
                "timestamp": f"{fmt_time(m.start)} – {fmt_time(m.end)}",
                "duration": round(m.duration, 1),
                "link": src.link_at(m.start),
                "score": m.score,
                "signals": m.parts,
                "reason": "; ".join(m.reasons) or "pico combinado de sinais",
                "transcript": m.text,
                "titles": [],  # Fase 3 (Claude)
            }
            for name, m in clips
        ],
    }
    Workdir(out_dir.parent, out_dir.name).save_json("report.json", data)

    md = [f"# {src.title}", "", f"Fonte: {src.url}", ""]
    for n in notes:
        md.append(f"> {n}")
    if notes:
        md.append("")
    for c in data["clips"]:
        md += [
            f"## {c['file']} — score {c['score']:.0f}/100",
            "",
            f"- **Trecho original:** [{c['timestamp']}]({c['link']}) ({c['duration']:.0f} s)",
            f"- **Motivo:** {c['reason']}",
            f"- **Sinais (0–1):** " + ", ".join(f"{k} {v:.2f}" for k, v in c["signals"].items()),
            "",
            f"> {c['transcript'] or '(sem fala)'}",
            "",
        ]
        if c["titles"]:
            md += ["**Sugestões de título:**", *[f"{i}. {t}" for i, t in enumerate(c["titles"], 1)], ""]
    (out_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
