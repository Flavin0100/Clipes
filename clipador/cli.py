"""Interface de linha de comando: clipador <link> [--max-clips N] [--min S --max S]."""

from __future__ import annotations

import argparse
import sys

from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipador",
        description="Gera cortes verticais prontos para TikTok/Reels/Shorts a partir de um link.",
    )
    p.add_argument("url", help="Link de VOD da Twitch, vídeo/live do YouTube ou clipe")
    p.add_argument("--max-clips", type=int, help="Quantidade máxima de cortes")
    p.add_argument("--min", dest="min_seconds", type=int, help="Duração mínima do corte (s)")
    p.add_argument("--max", dest="max_seconds", type=int, help="Duração máxima do corte (s)")
    p.add_argument("--config", default="config.yaml", help="Arquivo de configuração")
    p.add_argument("--cookies-from-browser", help="Navegador para cookies (chrome, firefox...)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_config(args.config)
    print("Pipeline ainda não implementado (Fase 1 em construção).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
