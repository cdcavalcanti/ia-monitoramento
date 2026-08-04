"""Poller contínuo: a cada N segundos varre silêncios e tenta reprocessar.

O relatório diário também usa a mesma coleta. Aqui é a camada operacional
(5 min de silêncio não pode esperar o job das 08:00).
"""

from __future__ import annotations

import asyncio
import logging

from app.collectors import chatwoot_health
from app.config import get_settings
from app.services import metrics, ops_cache
from app.services.reprocess import enviar_lote

logger = logging.getLogger("monitor.chatwoot_poller")

_task: asyncio.Task | None = None
_stop = asyncio.Event()
_tick_lock = asyncio.Lock()


async def _loop() -> None:
    s = get_settings()
    intervalo = max(15.0, float(s.chatwoot_poll_seconds))
    logger.info("chatwoot poller ativo a cada %.0fs (silêncio>=%.0fmin)", intervalo, s.chatwoot_silence_minutes)
    # dá tempo do dash responder no boot antes da 1ª varredura pesada
    try:
        await asyncio.wait_for(_stop.wait(), timeout=8.0)
        return
    except asyncio.TimeoutError:
        pass

    while not _stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("tick do poller falhou")

        try:
            await asyncio.wait_for(_stop.wait(), timeout=intervalo)
            break
        except asyncio.TimeoutError:
            pass


async def _tick() -> None:
    # evita sobreposição se algum dia o intervalo for menor que a varredura
    if _tick_lock.locked():
        logger.warning("poller: tick anterior ainda rodando — pulando")
        return
    async with _tick_lock:
        await _tick_inner()


async def _tick_inner() -> None:
    s = get_settings()
    if not s.chatwoot_health_enabled:
        return
    if not (s.chatwoot_base_url and s.chatwoot_api_token and s.chatwoot_account_list):
        logger.warning("poller: credenciais Chatwoot incompletas (BASE_URL/TOKEN/ACCOUNTS)")
        return

    resultado = await chatwoot_health.coletar()
    if resultado["status"] != "ok":
        logger.warning("poller: coleta status=%s dados=%s", resultado["status"], resultado.get("dados"))
        return

    dados = resultado["dados"]
    elegiveis = list(dados.get("leads_elegiveis_reprocessamento") or [])
    tot = dados.get("totais") or {}
    ops_cache.set_chatwoot(dados, status="ok")
    logger.info(
        "poller: analisadas=%s elegiveis=%s pausados=%s",
        dados.get("conversas_analisadas"),
        tot.get("elegiveis"),
        tot.get("pausados_com_silencio"),
    )
    metrics.heartbeat(
        "chatwoot_poller",
        "ok",
        {
            "analisadas": dados.get("conversas_analisadas"),
            "elegiveis": tot.get("elegiveis"),
            "pausados": tot.get("pausados_com_silencio"),
        },
    )
    if elegiveis:
        metrics.record_reprocess(
            kind="captured",
            count=len(elegiveis),
            status="detected",
            detail=f"somente_hoje={dados.get('somente_hoje')}",
        )

    if elegiveis:
        envio = await enviar_lote(elegiveis)
        logger.info("poller reprocess: %s", envio.get("status"))


async def start() -> None:
    global _task
    s = get_settings()
    if not s.chatwoot_health_enabled:
        logger.info("CHATWOOT_HEALTH_ENABLED=false — poller off")
        return
    if float(s.chatwoot_poll_seconds) <= 0:
        logger.info("CHATWOOT_POLL_SECONDS<=0 — poller off")
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="chatwoot-poller")


async def stop() -> None:
    global _task
    _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
