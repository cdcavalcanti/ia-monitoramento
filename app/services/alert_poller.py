"""Poller 24h de alertas: WAHA (sessões) + Painel (quando ligado).

WAHA — anti-spam:
  • Só importa a borda WORKING ↔ fora de WORKING (não STARTING→FAILED→SCAN_QR).
  • Queda só vira WhatsApp depois de WAHA_ALERT_DEBOUNCE_SECONDS (default 5 min).
    Flip-flop STARTING/WORKING no mesmo minuto = silêncio.
  • Recuperação só se a queda chegou a ser notificada.
  • Digest opcional a cada WAHA_ALERT_DIGEST_MINUTES com totais (acompanhar sem flood).

Painel: continua alertando mudança de saúde/serviços (já agrupado por tick).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

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

# nome → {since: float, status: str, notified: bool}
_waha_pending_down: dict[str, dict[str, Any]] = {}
_waha_last_digest_ts: float = 0.0


def _waha_reset_runtime() -> None:
    global _waha_pending_down, _waha_last_digest_ts
    _waha_pending_down = {}
    _waha_last_digest_ts = 0.0


async def _tick_waha() -> None:
    global _waha_baseline_enviado, _waha_last_digest_ts
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

    if alert_state.observar("waha:coleta", "ok"):
        await enviar_alerta("Consulta WAHA recuperada.", titulo="Recuperação WAHA")

    dados = resultado["dados"] or {}
    ops_cache.set_waha(dados, status="ok")
    metrics.heartbeat("waha", "ok", (dados.get("totais") or {}))

    primeira_passada = not _waha_baseline_enviado
    agora = time.monotonic()
    debounce = max(60.0, float(s.waha_alert_debounce_seconds))

    confirmados_ruim: list[str] = []
    recuperados: list[str] = []

    for sess in dados.get("sessoes") or []:
        nome = str(sess.get("name") or "?")
        st = str(sess.get("status") or "UNKNOWN")
        ok = bool(sess.get("ok"))
        chave = f"waha:session:{nome}"
        # Estado interno completo (dash/cache) — sem WhatsApp por flip intermediário.
        valor_detalhe = f"{'ok' if ok else 'ruim'}:{st}"
        if primeira_passada:
            alert_state.observar(chave, valor_detalhe)
            continue

        prev = alert_state.snapshot().get(chave)
        alert_state.observar(chave, valor_detalhe)

        if ok:
            pend = _waha_pending_down.pop(nome, None)
            if pend and pend.get("notified"):
                recuperados.append(f"{nome}=`WORKING`")
            # flip-flop curto: caiu e voltou antes do debounce → sem mensagem
            continue

        # Fora de WORKING
        pend = _waha_pending_down.get(nome)
        if pend is None:
            estava_ok = prev is None or str(prev).startswith("ok:")
            _waha_pending_down[nome] = {
                "since": agora,
                "status": st,
                # Já estava down antes (baseline/restart): não spamma; só borda ok→ruim conta.
                "notified": not estava_ok,
            }
            continue

        pend["status"] = st
        if pend.get("notified"):
            # Ainda down: ignora STARTING→FAILED→SCAN_QR (sem novo Zap)
            continue

        if (agora - float(pend["since"])) >= debounce:
            pend["notified"] = True
            confirmados_ruim.append(f"{nome}=`{st}`")

    if primeira_passada:
        tot = dados.get("totais") or {}
        _waha_baseline_enviado = True
        logger.info(
            "WAHA baseline (sem WhatsApp): total=%s working=%s ruins=%s — "
            "alerta só após %.0fs fora de WORKING; digest=%.0fmin",
            tot.get("total"),
            tot.get("working"),
            tot.get("ruins"),
            debounce,
            float(s.waha_alert_digest_minutes),
        )
        return

    if confirmados_ruim:
        lista = "\n".join(f"• {x}" for x in confirmados_ruim[:20])
        mais = f"\n… +{len(confirmados_ruim) - 20}" if len(confirmados_ruim) > 20 else ""
        await enviar_alerta(
            f"{len(confirmados_ruim)} sessão(ões) fora de WORKING "
            f"(≥{int(debounce // 60)} min):\n{lista}{mais}",
            titulo="Alerta WAHA — sessões",
        )
    if recuperados:
        lista = "\n".join(f"• {x}" for x in recuperados[:20])
        mais = f"\n… +{len(recuperados) - 20}" if len(recuperados) > 20 else ""
        await enviar_alerta(
            f"{len(recuperados)} sessão(ões) voltaram a WORKING:\n{lista}{mais}",
            titulo="Recuperação WAHA",
        )

    # Digest: acompanhar o quadro geral sem 1 msg por flip
    digest_min = float(s.waha_alert_digest_minutes)
    if digest_min > 0:
        intervalo = digest_min * 60.0
        if _waha_last_digest_ts <= 0:
            _waha_last_digest_ts = agora
        elif (agora - _waha_last_digest_ts) >= intervalo:
            tot = dados.get("totais") or {}
            ruins_n = int(tot.get("ruins") or 0)
            _waha_last_digest_ts = agora
            if ruins_n > 0:
                nomes = [
                    str(x.get("name") or "?")
                    for x in (dados.get("ruins") or [])[:12]
                    if isinstance(x, dict)
                ]
                amostra = ", ".join(nomes) if nomes else "—"
                extra = f" (+{ruins_n - 12})" if ruins_n > 12 else ""
                await enviar_alerta(
                    f"Digest WAHA (a cada {int(digest_min)} min)\n"
                    f"WORKING `{tot.get('working')}` · ruins `{ruins_n}` · total `{tot.get('total')}`\n"
                    f"Amostra ruins: {amostra}{extra}\n"
                    f"_Detalhe vivo no dash do monitor._",
                    titulo="Digest WAHA",
                )
            else:
                logger.info("digest WAHA: tudo WORKING — sem WhatsApp")


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
    logger.info(
        "alert poller a cada %.0fs | WAHA debounce=%.0fs digest=%.0fmin",
        intervalo,
        float(s.waha_alert_debounce_seconds),
        float(s.waha_alert_digest_minutes),
    )
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
    _waha_reset_runtime()
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
