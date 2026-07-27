"""Persistência local dos relatórios (markdown + snapshot JSON).

Arquivos: data/relatorios/YYYY-MM-DD_HHMM.md|.json
Slots padrão: 08:00 (manhã) e 18:00 (tarde).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("monitor.store")


def _dir() -> Path:
    s = get_settings()
    s.ensure_dirs()
    return s.data_dir / "relatorios"


def _stamp(quando: datetime | None = None) -> str:
    tz_name = get_settings().report_timezone
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
    dt = quando or datetime.now(tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d_%H%M")


def _paths(stamp: str) -> tuple[Path, Path]:
    base = _dir() / stamp
    return base.with_suffix(".md"), base.with_suffix(".json")


def salvar(
    relatorio_md: str,
    snapshot: dict[str, Any],
    *,
    stamp: str | None = None,
    rotulo: str = "",
) -> dict[str, str]:
    st = stamp or _stamp()
    md_path, json_path = _paths(st)
    payload = {
        "salvo_em": datetime.now(timezone.utc).isoformat(),
        "stamp": st,
        "rotulo": rotulo,
        "relatorio_md": relatorio_md,
        "snapshot": snapshot,
    }
    md_path.write_text(relatorio_md, encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("relatório salvo em %s", md_path)
    return {"markdown": str(md_path), "json": str(json_path), "stamp": st}


def existe_stamp(stamp: str) -> bool:
    _, json_path = _paths(stamp)
    return json_path.exists()


def carregar_ultimo() -> dict[str, Any] | None:
    pasta = _dir()
    jsons = sorted(pasta.glob("*.json"), reverse=True)
    if not jsons:
        return None
    try:
        return json.loads(jsons[0].read_text(encoding="utf-8"))
    except Exception:
        logger.exception("falha ao ler %s", jsons[0])
        return None


def carregar_stamp(stamp: str) -> dict[str, Any] | None:
    _, json_path = _paths(stamp)
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("falha ao ler %s", json_path)
        return None


def carregar_dia(dia: date) -> dict[str, Any] | None:
    """Compat: devolve o mais recente do dia, se houver."""
    prefix = dia.isoformat()
    pasta = _dir()
    jsons = sorted([p for p in pasta.glob(f"{prefix}*.json")], reverse=True)
    if not jsons:
        # legado YYYY-MM-DD.json
        legado = pasta / f"{prefix}.json"
        if legado.exists():
            jsons = [legado]
        else:
            return None
    try:
        return json.loads(jsons[0].read_text(encoding="utf-8"))
    except Exception:
        logger.exception("falha ao ler %s", jsons[0])
        return None


_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")


def stamp_de_horario(hora: int, minuto: int, dia: date | None = None) -> str:
    d = dia or date.today()
    return f"{d.isoformat()}_{hora:02d}{minuto:02d}"
