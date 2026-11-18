"""Carregamento de configuração: padrão do pacote + ./config.yaml + .env."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).with_name("default_config.yaml")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = "config.yaml") -> dict[str, Any]:
    with DEFAULT_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if path and Path(path).exists():
        with Path(path).open(encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return cfg


def resolve_asset(p: str | Path) -> Path:
    """Acha um asset relativo ao diretório atual ou à raiz do projeto."""
    p = Path(p)
    if p.is_absolute() or p.exists():
        return p
    alt = PROJECT_ROOT / p
    return alt if alt.exists() else p


def has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
