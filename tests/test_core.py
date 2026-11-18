import numpy as np

from clipador import captions, detect
from clipador.config import load_config
from clipador.download import SAMPLE_RATE, align


def W(text, s, e):
    return {"w": text, "s": s, "e": e, "p": 1.0}


def test_config_defaults_and_override(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("clips:\n  max_clips: 9\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["clips"]["max_clips"] == 9
    assert cfg["clips"]["min_seconds"] == 20  # veio do padrão


def test_find_peaks_respects_separation():
    x = np.zeros(1000, dtype=np.float32)
    x[100], x[110], x[500] = 5, 4, 3
    assert detect.find_peaks(x, 5, sep=30) == [100, 500]


def test_select_removes_overlap():
    a = detect.Moment(peak=50, start=30, end=70, score=90)
    b = detect.Moment(peak=60, start=40, end=80, score=80)
    c = detect.Moment(peak=200, start=180, end=220, score=70)
    assert detect.select([a, b, c], 5, gap=5) == [a, c]


def test_bounds_on_sentence_edges_without_cutting_words():
    cfg = load_config(None)
    words, t = [], 0.0
    for i in range(40):  # frases de 4 palavras, 2,4 s cada
        for j in range(4):
            words.append(W(f"p{i}_{j}" + ("." if j == 3 else ""), t, t + 0.5))
            t += 0.6
        t += 0.3
    s, e = detect.choose_bounds(50.0, words, cfg, total=200)
    assert 20 <= e - s <= 60
    assert s < 50 < e
    # início e fim não caem no meio de uma palavra
    assert not any(w["s"] < s < w["e"] for w in words)
    assert not any(w["s"] < e < w["e"] for w in words)


def test_chat_delay_and_reactions():
    msgs = [[20.0, "KEKW"], [20.5, "kkkkkk"], [21.0, "oi"]]
    rate, react = detect.chat_per_second(msgs, 100, ["KEKW"], delay=8)
    assert rate[12] == 2 and react[12] == 2 and rate[13] == 1 and react[13] == 0


def test_align_finds_offset():
    rng = np.random.default_rng(0)
    full = (rng.standard_normal(SAMPLE_RATE * 60) * 3000).astype(np.int16)
    true = 23.437
    sec = full[int(true * SAMPLE_RATE): int(true * SAMPLE_RATE) + SAMPLE_RATE * 14]
    got = align(sec, full, guess=25.0)
    assert abs(got - true) < 0.002


def test_captions_groups_and_fixes(tmp_path):
    cfg = load_config(None)
    words = [W("cá", 0, .2), W("cá", .2, .4), W("cá", .4, .6), W("olha", 1, 1.3), W("isso,", 1.3, 1.6),
             W("mano!", 1.7, 2.0)]
    fixed = captions.apply_fixes(words, {"cá cá cá": "kkk"})
    assert [w["w"] for w in fixed][:2] == ["kkk", "olha"]
    out = captions.build_ass(words, 0, 3, cfg, tmp_path / "c.ass")
    txt = out.read_text(encoding="utf-8")
    assert "KKK" in txt and "OLHA" in txt and "ISSO," not in txt
    assert txt.count("Dialogue:") == 4
