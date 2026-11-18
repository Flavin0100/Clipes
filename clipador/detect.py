"""Detecção de momentos.

Etapa 1 (barata, roda na live inteira): sinais por segundo de chat e áudio →
picos candidatos.
Etapa 2 (só nos candidatos, depois da transcrição): heurísticas de texto (ou
Claude, na Fase 3) → score final 0–100, limites do corte em fim de frase,
remoção de sobreposição e top N.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

import numpy as np

from .download import SAMPLE_RATE

log = logging.getLogger("clipador")


# --------------------------------------------------------------------------- sinais

def loudness_per_second(audio: np.ndarray) -> np.ndarray:
    """Energia RMS em dB por segundo."""
    n = len(audio) // SAMPLE_RATE
    out = np.empty(n, dtype=np.float32)
    chunk = 600  # segundos por bloco (não carrega tudo de uma vez)
    for i in range(0, n, chunk):
        j = min(n, i + chunk)
        a = np.asarray(audio[i * SAMPLE_RATE: j * SAMPLE_RATE], dtype=np.float32).reshape(j - i, SAMPLE_RATE)
        rms = np.sqrt(np.mean(a * a, axis=1)) / 32768.0
        out[i:j] = 20 * np.log10(rms + 1e-6)
    return out


def chat_per_second(msgs: list[list], n: int, tokens: list[str], delay: float) -> tuple[np.ndarray, np.ndarray]:
    """(mensagens/s, reações/s), já deslocados para trás por ``delay``."""
    rate = np.zeros(n, dtype=np.float32)
    react = np.zeros(n, dtype=np.float32)
    pats = [re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in tokens if t[0].isalnum()]
    raw = [t for t in tokens if not t[0].isalnum()]
    laugh = re.compile(r"k{4,}|(ha){3,}|(rs){3,}", re.I)
    for t, text in msgs:
        i = int(t - delay)
        if 0 <= i < n:
            rate[i] += 1
            if laugh.search(text) or any(p.search(text) for p in pats) or any(r in text for r in raw):
                react[i] += 1
    return rate, react


def smooth(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1 or len(x) == 0:
        return x.astype(np.float32)
    k = np.ones(w, dtype=np.float32) / w
    return np.convolve(x, k, mode="same").astype(np.float32)


def rolling_z(x: np.ndarray, w: int) -> np.ndarray:
    """Z-score em relação à média/desvio móveis (centrados) de ``w`` segundos."""
    n = len(x)
    if n == 0:
        return x
    w = max(3, min(w, n))
    c1 = np.concatenate([[0], np.cumsum(x, dtype=np.float64)])
    c2 = np.concatenate([[0], np.cumsum(x.astype(np.float64) ** 2)])
    idx = np.arange(n)
    lo = np.clip(idx - w // 2, 0, n)
    hi = np.clip(idx + w // 2 + 1, 0, n)
    cnt = hi - lo
    mean = (c1[hi] - c1[lo]) / cnt
    var = np.maximum((c2[hi] - c2[lo]) / cnt - mean ** 2, 0)
    std = np.sqrt(var)
    floor = max(float(np.std(x)) * 0.25, 1e-3)
    return ((x - mean) / np.maximum(std, floor)).astype(np.float32)


def squash(z: float, k: float = 2.0) -> float:
    """z-score → 0..1 (0 = normal, ~0.86 em z=4)."""
    return 1.0 - math.exp(-max(z, 0.0) / k)


@dataclass
class Signals:
    loud_db: np.ndarray
    audio_z: np.ndarray
    chat_z: np.ndarray | None
    chat_rate: np.ndarray | None
    chat_react: np.ndarray | None
    combined: np.ndarray


def build_signals(audio: np.ndarray, msgs: list[list] | None, cfg: dict) -> Signals:
    d = cfg["detect"]
    sm, base = int(d["smooth_seconds"]), int(d["baseline_seconds"])
    loud = loudness_per_second(audio)
    n = len(loud)
    # Picos de energia: nível relativo à vizinhança + subida brusca.
    audio_z = rolling_z(smooth(loud, sm), base)
    rise = np.concatenate([[0], np.diff(smooth(loud, 2))]).astype(np.float32)
    audio_z = audio_z + 0.3 * np.maximum(rolling_z(rise, base), 0)

    w = d["weights"]
    chat_z = rate = react = None
    if msgs:
        rate, react = chat_per_second(msgs, n, d["chat"]["reaction_tokens"], float(d["chat"]["delay_seconds"]))
        chat_z = rolling_z(smooth(rate + 2.0 * react, sm), base)
        wc, wa = float(w["chat"]), float(w["audio"])
    else:
        wc, wa = 0.0, 1.0
    tot = wc + wa
    comb = (wa / tot) * np.maximum(audio_z, 0)
    if chat_z is not None:
        comb = comb + (wc / tot) * np.maximum(chat_z, 0)
    return Signals(loud, audio_z, chat_z, rate, react, smooth(comb, 3))


def find_peaks(x: np.ndarray, k: int, sep: int, edge: int = 0) -> list[int]:
    """Top-k picos com supressão de não-máximos (distância mínima ``sep``)."""
    x = x.astype(np.float64)
    if edge and len(x) > 4 * edge:
        x[:edge] = -np.inf
        x[-edge:] = -np.inf
    peaks = []
    for _ in range(k):
        i = int(np.argmax(x))
        if x[i] <= 0:
            break
        peaks.append(i)
        x[max(0, i - sep): i + sep + 1] = -np.inf
    return peaks


# --------------------------------------------------------------------------- momentos

@dataclass
class Moment:
    peak: float
    start: float = 0.0
    end: float = 0.0
    score: float = 0.0
    parts: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    text: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


def sentences(words: list[dict], gap: float = 0.8) -> list[list[dict]]:
    """Agrupa palavras em frases: quebra em pontuação final ou pausa longa."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and w["s"] - cur[-1]["e"] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def choose_bounds(peak: float, words: list[dict], cfg: dict, total: float) -> tuple[float, float]:
    """Escolhe [início, fim] em limites de frase, com o pico a ~60% do corte."""
    c = cfg["clips"]
    mn, mx = float(c["min_seconds"]), float(c["max_seconds"])
    target = mn + 0.4 * (mx - mn)
    want_s, want_e = peak - 0.6 * target, peak + 0.4 * target
    sents = sentences(words)
    starts = [s[0]["s"] for s in sents if peak - (mx - 3) <= s[0]["s"] <= peak - 1]
    ends = [s[-1]["e"] for s in sents if s[-1]["e"] >= peak + 2]
    best, best_cost = None, math.inf
    for s in starts:
        for e in ends:
            d = e - s
            if mn <= d <= mx - 1:
                cost = abs(s - want_s) + abs(e - want_e)
                if cost < best_cost:
                    best, best_cost = (s, e), cost
    if best is None:  # pouca fala: janela fixa em volta do pico
        s = max(0.0, want_s)
        best = (s, min(total, s + target))
        return best

    s, e = best
    # Pré-roll de alguns segundos, sem pegar meia palavra da frase anterior.
    prev_end = max([w["e"] for w in words if w["e"] <= s - 0.01], default=-math.inf)
    s = max(s - float(c["pre_roll_seconds"]), prev_end + 0.05, e - mx, 0.0)
    nxt = min([w["s"] for w in words if w["s"] >= e - 0.01], default=math.inf)
    e = min(e + float(c["post_roll_seconds"]), nxt - 0.05, total)
    return s, e


def _reaction_hits(text: str, vocab: list[str]) -> list[tuple[str, int]]:
    hits = []
    for rw in vocab:
        n = len(re.findall(r"(?<!\w)" + re.escape(rw.lower()) + r"\w*", text))
        if n:
            hits.append((rw, n))
    return hits


def text_score(words: list[dict], peak: float, cfg: dict) -> tuple[float, list[str]]:
    """Heurística de texto (substitui o Claude quando não há chave da API).

    Mede reações e exclamações perto do pico em relação ao resto da janela
    transcrita: o que importa é a fala *mudar* no momento, não o streamer
    falar palavrão o tempo todo.
    """
    vocab = cfg["detect"]["text"]["reaction_words"]

    def density(ws: list[dict], secs: float) -> tuple[float, list[tuple[str, int]]]:
        text = " ".join(w["w"] for w in ws).lower()
        hits = _reaction_hits(text, vocab)
        raw = sum(n for _, n in hits) + 0.5 * (text.count("!") + text.count("?"))
        return raw / max(secs, 1.0), hits

    near = [w for w in words if peak - 15 <= w["s"] <= peak + 10]
    rest = [w for w in words if not (peak - 15 <= w["s"] <= peak + 10)]
    span = (max((w["e"] for w in words), default=0) - min((w["s"] for w in words), default=0)) - 25
    d_near, hits = density(near, 25)
    d_rest, _ = density(rest, span)
    lift = (d_near - d_rest) * 25          # reações "a mais" que o normal nesses 25 s
    reasons = [f"fala: {', '.join(f'“{h}”' for h, _ in sorted(hits, key=lambda x: -x[1])[:4])}"] if hits else []
    return 1.0 - math.exp(-max(lift, 0.0) / 3.0), reasons


def score_moments(peaks: list[int], sig: Signals, segs: list[dict], cfg: dict, total: float) -> list[Moment]:
    from .transcribe import words_in

    w = cfg["detect"]["weights"]
    weights = {"audio": float(w["audio"]), "semantic": float(w["semantic"])}
    if sig.chat_z is not None:
        weights["chat"] = float(w["chat"])
    wsum = sum(weights.values())
    moments = []
    for p in peaks:
        lo, hi = max(0, p - 6), min(len(sig.combined), p + 7)
        m = Moment(peak=float(p))
        parts: dict[str, float] = {}
        a_z = float(np.max(sig.audio_z[lo:hi]))
        parts["audio"] = squash(a_z)
        db_gain = float(np.max(sig.loud_db[lo:hi]) - np.median(sig.loud_db[max(0, p - 150): p + 150]))
        if a_z > 1.5:
            m.reasons.append(f"áudio +{db_gain:.0f} dB acima do normal")
        if sig.chat_z is not None:
            c_z = float(np.max(sig.chat_z[lo:hi]))
            parts["chat"] = squash(c_z)
            base = float(np.mean(sig.chat_rate[max(0, p - 150): p + 150])) + 1e-6
            now = float(np.mean(sig.chat_rate[lo:hi]))
            reacts = int(np.sum(sig.chat_react[lo:hi]))
            if c_z > 1.0:
                m.reasons.append(f"chat {now / base:.1f}x mais rápido que o normal ({reacts} reações)")
        words = words_in(segs, p - cfg["clips"]["max_seconds"] - 5, p + cfg["clips"]["max_seconds"])
        parts["semantic"], why = text_score(words, p, cfg)
        m.reasons += why
        m.parts = {k: round(v, 3) for k, v in parts.items()}
        m.score = round(100 * sum(weights[k] * parts[k] for k in weights) / wsum, 1)
        m.start, m.end = choose_bounds(p, words, cfg, total)
        m.text = " ".join(x["w"] for x in words if m.start <= x["s"] and x["e"] <= m.end)
        moments.append(m)
    return moments


def select(moments: list[Moment], n: int, gap: float) -> list[Moment]:
    """Top N sem sobreposição (com distância mínima ``gap``)."""
    chosen: list[Moment] = []
    for m in sorted(moments, key=lambda x: -x.score):
        if all(m.end + gap <= c.start or m.start >= c.end + gap for c in chosen):
            chosen.append(m)
        if len(chosen) >= n:
            break
    return chosen
