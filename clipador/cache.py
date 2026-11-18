"""Cache por etapa.

Cada vídeo tem uma pasta ``cache/<id>/``. Cada etapa grava seu artefato lá;
se o artefato já existe, a etapa é pulada. Escritas são atômicas (arquivo
temporário + rename), então uma queda no meio não deixa arquivo corrompido.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def safe_name(text: str, max_len: int = 80) -> str:
    """Nome seguro para pasta/arquivo no Windows e no Linux."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    return (text[:max_len].rstrip() or "video")


class Workdir:
    def __init__(self, root: Path | str, key: str):
        self.dir = Path(root) / safe_name(key)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def has(self, name: str) -> bool:
        p = self.dir / name
        return p.exists() and p.stat().st_size > 0

    def load_json(self, name: str) -> Any:
        with (self.dir / name).open(encoding="utf-8") as f:
            return json.load(f)

    def save_json(self, name: str, data: Any) -> Path:
        p = self.path(name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return p
