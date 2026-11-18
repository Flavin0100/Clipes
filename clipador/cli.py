"""Linha de comando: clipador <link> [--max-clips N] [--min S --max S]."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipador",
        description="Gera cortes verticais prontos para TikTok/Reels/Shorts a partir de um link.",
    )
    p.add_argument("url", help="Link de VOD da Twitch, vídeo/live do YouTube, clipe ou arquivo local")
    p.add_argument("--max-clips", type=int, help="Quantidade máxima de cortes")
    p.add_argument("--min", dest="min_seconds", type=int, help="Duração mínima do corte (s)")
    p.add_argument("--max", dest="max_seconds", type=int, help="Duração máxima do corte (s)")
    p.add_argument("--config", default="config.yaml", help="Arquivo de configuração (opcional)")
    p.add_argument("--cookies-from-browser", help="Navegador para cookies (chrome, firefox, edge...)")
    p.add_argument("--model", help="Modelo do Whisper (small, medium, large-v3-turbo...)")
    p.add_argument("--layout", choices=["center", "blur_background"], help="Layout sem facecam")
    p.add_argument("-v", "--verbose", action="store_true", help="Log detalhado")
    return p


def apply_args(cfg: dict, a: argparse.Namespace) -> dict:
    if a.max_clips:
        cfg["clips"]["max_clips"] = a.max_clips
    if a.min_seconds:
        cfg["clips"]["min_seconds"] = a.min_seconds
    if a.max_seconds:
        cfg["clips"]["max_seconds"] = a.max_seconds
    if cfg["clips"]["min_seconds"] >= cfg["clips"]["max_seconds"]:
        raise SystemExit("--min precisa ser menor que --max")
    if a.cookies_from_browser:
        cfg["download"]["cookies_from_browser"] = a.cookies_from_browser
    if a.model:
        cfg["transcribe"]["model"] = a.model
    if a.layout:
        cfg["layout"]["no_facecam"] = a.layout
    return cfg


def setup_logging(verbose: bool) -> None:
    try:
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(show_path=False, markup=False, log_time_format="%H:%M:%S")
        fmt = "%(message)s"
    except ImportError:
        handler, fmt = logging.StreamHandler(), "%(asctime)s %(message)s"
    logging.basicConfig(level=logging.WARNING, format=fmt, handlers=[handler], datefmt="%H:%M:%S")
    logging.getLogger("clipador").setLevel(logging.DEBUG if verbose else logging.INFO)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    cfg = apply_args(load_config(args.config), args)
    from .pipeline import run_pipeline

    try:
        run_pipeline(args.url, cfg)
    except KeyboardInterrupt:
        print("\nInterrompido. Rode o mesmo comando para continuar de onde parou.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
