"""Scheduler: relatórios em horários configuráveis (default 08:00 e 18:00).

O serviço fica 24h no ar. Este loop só dispara os relatórios consolidados.
Chatwoot / alertas de Painel / WAHA rodam em pollers separados.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services import store

logger = logging.getLogger("monitor.scheduler")

_task: asyncio.Task | None = None
_stop = asyncio.Event()


def _tz():
    s = get_settings()
    try:
        return ZoneInfo(s.report_timezone)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def horarios_relatorio() -> list[tuple[int, int]]:
    """Lê REPORT_TIMES=08:00,18:00 — fallback REPORT_HOUR/MINUTE."""
    s = get_settings()
    raw = (s.report_times or "").strip()
    out: list[tuple[int, int]] = []
    if raw:
        for parte in raw.split(","):
            parte = parte.strip()
            if not parte or ":" not in parte:
                continue
            h, m = parte.split(":", 1)
            try:
                out.append((int(h), int(m)))
            except ValueError:
                continue
    if not out:
        out = [(int(s.report_hour), int(s.report_minute))]
    return sorted(set(out))


def _proximo_disparo() -> tuple[datetime, int, int]:
    tz = _tz()
    agora = datetime.now(tz)
    candidatos: list[tuple[datetime, int, int]] = []
    for h, m in horarios_relatorio():
        alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        if alvo <= agora:
            alvo = alvo + timedelta(days=1)
        candidatos.append((alvo, h, m))
    candidatos.sort(key=lambda x: x[0])
    return candidatos[0]


def _rotulo(hora: int, minuto: int) -> str:
    if hora < 12:
        return "manha"
    if hora < 17:
        return "tarde"
    return "fim_do_dia"


async def _loop() -> None:
    from app.services.pipeline import gerar_relatorio_diario

    slots = ", ".join(f"{h:02d}:{m:02d}" for h, m in horarios_relatorio())
    s = get_settings()
    logger.info("scheduler ativo: %s (%s)", slots, s.report_timezone)

    while not _stop.is_set():
        alvo, hora, minuto = _proximo_disparo()
        espera = max(1.0, (alvo - datetime.now(_tz())).total_seconds())
        logger.info("próximo relatório em %.0fs (%s)", espera, alvo.isoformat())
        try:
            await asyncio.wait_for(_stop.wait(), timeout=espera)
            break
        except asyncio.TimeoutError:
            pass

        if _stop.is_set():
            break

        stamp = store.stamp_de_horario(hora, minuto, date.today())
        # Se o relógio atrasou e já passou do minuto, ainda usa o stamp do slot.
        if store.existe_stamp(stamp):
            logger.info("relatório %s já existe — pulando", stamp)
            try:
                await asyncio.wait_for(_stop.wait(), timeout=61)
                break
            except asyncio.TimeoutError:
                continue

        rotulo = _rotulo(hora, minuto)
        try:
            resultado = await gerar_relatorio_diario(
                enviar=True,
                forcar=True,
                stamp=stamp,
                rotulo=rotulo,
            )
            logger.info("job %s ok: %s", rotulo, resultado.get("paths"))
        except Exception:
            logger.exception("job %s falhou", rotulo)


async def start() -> None:
    global _task
    s = get_settings()
    if not s.scheduler_enabled:
        logger.info("SCHEDULER_ENABLED=false — sem job automático")
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="monitor-scheduler")


async def stop() -> None:
    global _task
    _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
