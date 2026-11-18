"""Layout 9:16 (filtros do ffmpeg).

Fase 1: ``center`` (crop central) e ``blur_background`` (vídeo inteiro no meio
com fundo desfocado). Fase 2 adiciona facecam + gameplay e crop por movimento.
"""

from __future__ import annotations


def video_filter(cfg: dict) -> str:
    """Filtro que leva [0:v] para [v] em WxH."""
    lay = cfg["layout"]
    W, H = int(lay["width"]), int(lay["height"])
    mode = lay.get("no_facecam", "center")
    if mode == "blur_background":
        return (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=luma_radius=40:luma_power=2,eq=brightness=-0.08[bgb];"
            f"[fg]scale={W}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
        )
    # center: corta a faixa central no aspecto 9:16 e escala.
    return (
        f"[0:v]crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',"
        f"scale={W}:{H}:flags=lanczos,setsar=1[v]"
    )
