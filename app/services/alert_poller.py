"""Poller 24h de alertas: WAHA (sessões) + Painel (quando ligado).

Dispara WhatsApp só quando o status MUDA (queda / recuperação),
não a cada minuto com o mesmo problema.
"""

from __future__ import annotations

import asyncio
import logging

from app.collectors import painel, waha_health
from app.config import get_settings
from app.services.alert_state import alert_state
from app.services.delivery import enviar_alerta

logger = logging.getLogger("monitor.alert_poller")

_task: asyncio.Task | None = None
_stop = asyncio.Event()


async def _tick_waha() -> None:
    s = get_settings()
    if not s.waha_health_enabled:
        return
    resultado = await waha_health.coletar()
    if resultado["status"] != "ok":
        chave = "waha:coleta"
        status = resultado["status"]
        if alert_state.mudou(chave, status):
            await enviar_alerta(
                f"Falha ao consultar sessões WAHA.\nStatus: {status}\n{resultado.get('dados')}",
                titulo="Alerta WAHA",
            )
        return

    dados = resultado["dados"] or {}
    for sess in dados.get("sessoes") or []:
        nome = sess.get("name") or "?"
        st = str(sess.get("status") or "UNKNOWN")
        chave = f"waha:session:{nome}"
        # normaliza para comparação
        nivel = "ok" if sess.get("ok") else "ruim"
        if alert_state.mudou(chave, f"{nivel}:{st}"):
            if nivel == "ruim":
                await enviar_alerta(
                    f"Sessão WAHA *{nome}* não está WORKING.\nStatus atual: `{st}`",
                    titulo="Alerta WAHA — sessão",
                )
            else:
                await enviar_alerta(
                    f"Sessão WAHA *{nome}* voltou.\nStatus: `{st}`",
                    titulo="Recuperação WAHA",
                )


async def _tick_painel() -> None:
    s = get_settings()
    if not s.painel_enabled:
        return
    resultado = await painel.coletar()
    if resultado["status"] != "ok":
        chave = "painel:coleta"
        if alert_state.mudou(chave, resultado["status"]):
            await enviar_alerta(
                f"Falha ao consultar Painel de Serviços.\n{resultado.get('dados')}",
                titulo="Alerta Painel",
            )
        return

    dados = resultado["dados"] or {}
    # Formato ainda genérico até a API oficial. Aceita overview com lista de serviços.
    overview = dados.get("overview") or dados
    servicos = []
    if isinstance(overview, dict):
        for key in ("servicos", "services", "items", "clientes"):
            if isinstance(overview.get(key), list):
                servicos = overview[key]
                break
    if isinstance(overview, list):
        servicos = overview

    for item in servicos:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or item.get("name") or item.get("servico") or item.get("id") or "?")
        status = str(
            item.get("status") or item.get("estado") or item.get("health") or "unknown"
        ).lower()
        chave = f"painel:servico:{nome}"
        nivel = "ok" if status in ("ok", "up", "online", "healthy", "ativo") else "ruim"
        if alert_state.mudou(chave, f"{nivel}:{status}"):
            if nivel == "ruim":
                await enviar_alerta(
                    f"Serviço *{nome}* com problema.\nStatus: `{status}`",
                    titulo="Alerta Painel — serviço",
                )
            else:
                await enviar_alerta(
                    f"Serviço *{nome}* recuperado.\nStatus: `{status}`",
                    titulo="Recuperação Painel",
                )


async def _tick() -> None:
    await _tick_waha()
    await _tick_painel()


async def _loop() -> None:
    s = get_settings()
    intervalo = max(20.0, float(s.alert_poll_seconds))
    logger.info("alert poller ativo a cada %.0fs", intervalo)
    while not _stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("tick de alertas falhou")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=intervalo)
            break
        except asyncio.TimeoutError:
            pass


async def start() -> None:
    global _task
    s = get_settings()
    if not s.alert_poller_enabled:
        logger.info("ALERT_POLLER_ENABLED=false — poller de alertas off")
        return
    if not (s.waha_health_enabled or s.painel_enabled):
        logger.info("nenhuma fonte de alerta ligada (WAHA_HEALTH/PAINEL) — poller off")
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(), name="alert-poller")


async def stop() -> None:
    global _task
    _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
