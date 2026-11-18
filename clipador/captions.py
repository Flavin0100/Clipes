"""Legendas .ass estilo karaokê: 1–3 palavras por vez, palavra ativa em destaque."""

from __future__ import annotations

import re
from pathlib import Path


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def apply_fixes(words: list[dict], fixes: dict[str, str]) -> list[dict]:
    """Troca sequências de palavras (sem diferenciar maiúsculas) pelo texto corrigido."""
    if not fixes:
        return words
    rules = [(k.lower().split(), v) for k, v in fixes.items()]
    rules.sort(key=lambda r: -len(r[0]))
    norm = [re.sub(r"[^\w]", "", w["w"].lower()) for w in words]
    out, i = [], 0
    while i < len(words):
        for keys, repl in rules:
            k = len(keys)
            if [re.sub(r"[^\w]", "", x) for x in keys] == norm[i:i + k]:
                out.append({**words[i], "w": repl, "e": words[i + k - 1]["e"]})
                i += k
                break
        else:
            out.append(words[i])
            i += 1
    return out


def group_words(words: list[dict], max_words: int, max_chars: int, gap: float = 0.35) -> list[list[dict]]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
        if cur and (len(cur) >= max_words or chars > max_chars or w["s"] - cur[-1]["e"] > gap):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?…,]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _clean(word: str, upper: bool) -> str:
    word = re.sub(r"[.,;:…]+$", "", word)
    word = word.replace("\\", "").replace("{", "(").replace("}", ")")
    return word.upper() if upper else word


def build_ass(words: list[dict], clip_start: float, clip_end: float, cfg: dict, out: Path) -> Path:
    c = cfg["captions"]
    lay = cfg["layout"]
    W, H = int(lay["width"]), int(lay["height"])
    x, y = W // 2, int(H * float(c["position_y"]))
    prim, hi = ass_color(c["primary_color"]), ass_color(c["highlight_color"])
    outline = ass_color(c["outline_color"])
    shadow = ass_color("#000000", 0x60)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,{c['font']},{c['size']},{prim},{hi},{outline},{shadow},-1,0,0,0,100,100,0,0,1,{c['outline']},{c['shadow']},5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    words = [w for w in words if w["e"] > clip_start and w["s"] < clip_end]
    words = apply_fixes(words, c.get("fixes") or {})
    groups = group_words(words, int(c["max_words"]), int(c["max_chars"]))
    lines = []
    for gi, g in enumerate(groups):
        g_end = g[-1]["e"] + 0.25
        if gi + 1 < len(groups):
            g_end = min(g_end, groups[gi + 1][0]["s"])
        g_end = min(g_end, clip_end)
        for i, w in enumerate(g):
            s = w["s"] if i else max(w["s"], clip_start)
            e = g[i + 1]["s"] if i + 1 < len(g) else g_end
            if e - s < 0.02:
                continue
            parts = []
            for j, other in enumerate(g):
                txt = _clean(other["w"], bool(c["uppercase"]))
                if j == i:
                    parts.append(f"{{\\c{hi}\\fscx110\\fscy110}}{txt}{{\\c{prim}\\fscx100\\fscy100}}")
                else:
                    parts.append(txt)
            pop = "\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            text = f"{{\\an5\\pos({x},{y}){pop}}}" + " ".join(parts)
            lines.append(f"Dialogue: 0,{ass_time(s - clip_start)},{ass_time(e - clip_start)},Clip,,0,0,0,,{text}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out
