"""Poller 24h de alertas: WAHA (sessões) + Painel (quando ligado).

Dispara WhatsApp só quando o status MUDA (queda / recuperação),
não a cada minuto com o mesmo problema.

No primeiro ciclo após subir o processo: só grava baseline + 1 resumo
(WAHA), sem spam por sessão.
"""

from __future__ import annotations

import asyncio
import logging

from app.collectors import waha_health
from app.config import get_settings
from app.services import metrics, ops_cache
from app.services.alert_state import alert_state
from app.services.delivery import enviar_alerta

logger = logging.getLogger("monitor.alert_poller")

_task: asyncio.Task | None = None
_stop = asyncio.Event()
_waha_baseline_enviado = False
_painel_baseline_enviado = False


async def _tick_waha() -> None:
    global _waha_baseline_enviado
    s = get_settings()
    if not s.waha_health_enabled:
        return
    resultado = await waha_health.coletar()
    if resultado["status"] != "ok":
        chave = "waha:coleta"
        status = resultado["status"]
        metrics.heartbeat("waha", status, resultado.get("dados"))
        if alert_state.observar(chave, status):
            await enviar_alerta(
                f"Falha ao consultar sessões WAHA.\nStatus: {status}\n{resultado.get('dados')}",
                titulo="Alerta WAHA",
            )
        return

    # coleta ok — se estava em erro, avisa recuperação
    if alert_state.observar("waha:coleta", "ok"):
        await enviar_alerta("Consulta WAHA recuperada.", titulo="Recuperação WAHA")

    dados = resultado["dados"] or {}
    ops_cache.set_waha(dados, status="ok")
    metrics.heartbeat("waha", "ok", (dados.get("totais") or {}))

    mudancas_ruim: list[str] = []
    mudancas_ok: list[str] = []
    primeira_passada = not _waha_baseline_enviado

    for sess in dados.get("sessoes") or []:
        nome = sess.get("name") or "?"
        st = str(sess.get("status") or "UNKNOWN")
        chave = f"waha:session:{nome}"
        nivel = "ok" if sess.get("ok") else "ruim"
        valor = f"{nivel}:{st}"
        if primeira_passada:
            # só baseline
            alert_state.observar(chave, valor)
            continue
        if alert_state.observar(chave, valor):
            if nivel == "ruim":
                mudancas_ruim.append(f"{nome}=`{st}`")
            else:
                mudancas_ok.append(f"{nome}=`{st}`")

    if primeira_passada:
        tot = dados.get("totais") or {}
        _waha_baseline_enviado = True
        logger.info(
            "WAHA baseline (sem WhatsApp): total=%s working=%s ruins=%s — só alertará mudanças",
            tot.get("total"),
            tot.get("working"),
            tot.get("ruins"),
        )
        return

    # Agrupa mudanças num único WhatsApp (evita N msgs no mesmo tick)
    if mudancas_ruim:
        lista = "\n".join(f"• {x}" for x in mudancas_ruim[:20])
        mais = f"\n… +{len(mudancas_ruim) - 20}" if len(mudancas_ruim) > 20 else ""
        await enviar_alerta(
            f"{len(mudancas_ruim)} sessão(ões) saíram de WORKING:\n{lista}{mais}",
            titulo="Alerta WAHA — sessões",
        )
    if mudancas_ok:
        lista = "\n".join(f"• {x}" for x in mudancas_ok[:20])
        mais = f"\n… +{len(mudancas_ok) - 20}" if len(mudancas_ok) > 20 else ""
        await enviar_alerta(
            f"{len(mudancas_ok)} sessão(ões) recuperaram:\n{lista}{mais}",
            titulo="Recuperação WAHA",
        )


async def _tick_painel() -> None:
    global _painel_baseline_enviado
    s = get_settings()
    if not s.painel_enabled:
        return
    from app.collectors.painel import coletar_overview_leve

    resultado = await coletar_overview_leve()
    if resultado["status"] != "ok":
        chave = "painel:coleta"
        metrics.heartbeat("painel", resultado["status"], resultado.get("dados"))
        if alert_state.observar(chave, resultado["status"]):
            await enviar_alerta(
                f"Falha ao consultar Hub de Status.\n{resultado.get('dados')}",
                titulo="Alerta Painel",
            )
        return

    if alert_state.observar("painel:coleta", "ok"):
        await enviar_alerta("Hub de Status recuperado.", titulo="Recuperação Hub")

    dados = resultado["dados"] or {}
    ops_cache.set_painel(dados, status="ok")
    metrics.heartbeat("painel", "ok", dados.get("totais") or {})
    primeira = not _painel_baseline_enviado

    saude = str((dados.get("totais") or {}).get("saudeGeral") or "")
    if saude:
        if primeira:
            alert_state.observar("painel:saudeGeral", saude)
        elif alert_state.observar("painel:saudeGeral", saude) and saude in ("atencao", "critico"):
            alertas = (dados.get("normalizado") or {}).get("alertas_api") or []
            linhas = "\n".join(f"- {a}" for a in alertas[:8]) or "(sem detalhe)"
            await enviar_alerta(
                f"Saúde geral do Hub: *{saude}*\n{linhas}",
                titulo="Alerta Hub de Status",
            )

    mudancas: list[str] = []
    recuperos: list[str] = []
    for item in dados.get("servicos") or []:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "?")
        tipo = str(item.get("tipo") or "servico")
        status = str(item.get("status") or "unknown").lower()
        nivel = str(item.get("nivel") or "ruim")
        chave = f"painel:{tipo}:{nome}"
        valor = f"{nivel}:{status}"
        if primeira:
            alert_state.observar(chave, valor)
            continue
        if alert_state.observar(chave, valor):
            if nivel != "ok":
                mudancas.append(f"{tipo} `{nome}` → `{status}`")
            else:
                recuperos.append(f"{tipo} `{nome}` → `{status}`")

    if primeira:
        tot = dados.get("totais") or {}
        _painel_baseline_enviado = True
        logger.info(
            "Hub baseline (sem WhatsApp): saude=%s totais=%s — só alertará mudanças",
            saude,
            tot,
        )
        return

    if mudancas:
        lista = "\n".join(f"• {x}" for x in mudancas[:15])
        await enviar_alerta(f"Problemas no Hub:\n{lista}", titulo="Alerta Hub de Status")
    if recuperos:
        lista = "\n".join(f"• {x}" for x in recuperos[:15])
        await enviar_alerta(f"Recuperações no Hub:\n{lista}", titulo="Recuperação Hub")


async def _tick() -> None:
    await _tick_waha()
    await _tick_painel()


async def _loop() -> None:
    s = get_settings()
    intervalo = max(20.0, float(s.alert_poll_seconds))
    logger.info("alert poller ativo a cada %.0fs (baseline sem spam)", intervalo)
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
    global _task, _waha_baseline_enviado, _painel_baseline_enviado
    s = get_settings()
    if not s.alert_poller_enabled:
        logger.info("ALERT_POLLER_ENABLED=false — poller de alertas off")
        return
    if not (s.waha_health_enabled or s.painel_enabled):
        logger.info("nenhuma fonte de alerta ligada (WAHA_HEALTH/PAINEL) — poller off")
        return
    _waha_baseline_enviado = False
    _painel_baseline_enviado = False
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
