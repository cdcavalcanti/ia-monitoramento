"""Relógio operacional do monitor — sempre America/Sao_Paulo (config)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def tz_ops() -> ZoneInfo:
    try:
        from app.config import get_settings

        nome = (get_settings().report_timezone or "America/Sao_Paulo").strip()
        return ZoneInfo(nome)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def agora_ops() -> datetime:
    """Agora no fuso do relatório (default America/Sao_Paulo)."""
    return datetime.now(tz_ops())


def hoje_ops() -> date:
    return agora_ops().date()


def hoje_iso() -> str:
    return hoje_ops().isoformat()


def hoje_br() -> str:
    """Ex.: 03/08/2026"""
    d = hoje_ops()
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def agora_br() -> str:
    """Ex.: 03/08/2026 12:58"""
    dt = agora_ops()
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year} {dt.hour:02d}:{dt.minute:02d}"


def agora_iso() -> str:
    return agora_ops().isoformat()


def carimbo_relatorio() -> dict[str, str]:
    """Campos padrão pra snapshot / cabeçalho / prompt."""
    dt = agora_ops()
    return {
        "gerado_em": dt.isoformat(),
        "dia_operacional": dt.date().isoformat(),
        "dia_operacional_br": f"{dt.day:02d}/{dt.month:02d}/{dt.year}",
        "gerado_em_br": f"{dt.day:02d}/{dt.month:02d}/{dt.year} {dt.hour:02d}:{dt.minute:02d}",
        "fuso": str(dt.tzinfo) if dt.tzinfo else "America/Sao_Paulo",
    }
