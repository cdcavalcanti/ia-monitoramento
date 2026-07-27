"""Poller 24h de alertas: WAHA (sessões) + Painel (quando ligado).

Dispara WhatsApp só quando o status MUDA (queda / recuperação),
não a cada minuto com o mesmo problema.
"""

from __future__ import annotations

import asyncio
import logging

from app.collectors import waha_health
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
    # Overview leve — não chama /api/relatorio-diario no poller.
    from app.collectors.painel import coletar_overview_leve

    resultado = await coletar_overview_leve()
    if resultado["status"] != "ok":
        chave = "painel:coleta"
        if alert_state.mudou(chave, resultado["status"]):
            await enviar_alerta(
                f"Falha ao consultar Hub de Status.\n{resultado.get('dados')}",
                titulo="Alerta Painel",
            )
        return

    dados = resultado["dados"] or {}
    saude = str((dados.get("totais") or {}).get("saudeGeral") or "")
    if saude and alert_state.mudou("painel:saudeGeral", saude):
        if saude in ("atencao", "critico"):
            alertas = (dados.get("normalizado") or {}).get("alertas_api") or []
            linhas = "\n".join(f"- {a}" for a in alertas[:8]) or "(sem detalhe)"
            await enviar_alerta(
                f"Saúde geral do Hub: *{saude}*\n{linhas}",
                titulo="Alerta Hub de Status",
            )

    for item in dados.get("servicos") or []:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "?")
        tipo = str(item.get("tipo") or "servico")
        status = str(item.get("status") or "unknown").lower()
        nivel = str(item.get("nivel") or "ruim")
        chave = f"painel:{tipo}:{nome}"
        if alert_state.mudou(chave, f"{nivel}:{status}"):
            if nivel != "ok":
                await enviar_alerta(
                    f"*{tipo}* `{nome}` com problema.\nStatus: `{status}`",
                    titulo="Alerta Hub de Status",
                )
            else:
                await enviar_alerta(
                    f"*{tipo}* `{nome}` recuperado.\nStatus: `{status}`",
                    titulo="Recuperação Hub de Status",
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
