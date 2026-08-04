"""Pipeline: coletar → agregar → sintetizar (LLM) → salvar → entregar."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.collectors import chatwoot_health, gestao, painel
from app.collectors.base import resultado_erro, resultado_ok
from app.collectors.chatwoot_health import filtrar_leads_somente_hoje, snapshot_eh_de_hoje
from app.config import get_settings
from app.services import ops_cache, store
from app.services.aggregator import agregar
from app.services.delivery import enviar_whatsapp
from app.services.reprocess import enviar_lote

logger = logging.getLogger("monitor.pipeline")

# Relatório NÃO deve re-varrer Chatwoot inteiro (pode levar >10–20 min).
# Usa cache dos pollers 24h; Gestão continua fresca (é o núcleo do relatório).
# Cache Chatwoot só vale se for do dia corrente (America/Sao_Paulo).
_GESTAO_TIMEOUT = 180.0
_PAINEL_TIMEOUT = 60.0
_LAB_FALLBACK_TIMEOUT = 200.0


def _chatwoot_from_cache(cached: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    tz = s.report_timezone
    only_today = bool(cached.get("somente_hoje", True))
    elegiveis = list(cached.get("elegiveis") or [])
    pausados = list(cached.get("pausados") or [])
    if only_today:
        antes = len(elegiveis)
        elegiveis = filtrar_leads_somente_hoje(elegiveis, tz_name=tz)
        if antes and len(elegiveis) < antes:
            logger.info(
                "chatwoot cache: filtrou elegíveis fora de hoje (%s → %s)",
                antes,
                len(elegiveis),
            )
    totais = dict(cached.get("totais") or {})
    totais["elegiveis"] = len(elegiveis)
    totais["pausados_com_silencio"] = len(pausados)
    return {
        "silencio_minutos": cached.get("silencio_minutos"),
        "somente_hoje": cached.get("somente_hoje"),
        "totais": totais,
        "conversas_analisadas": cached.get("conversas_analisadas"),
        "contas": cached.get("por_conta") or [],
        "leads_elegiveis_reprocessamento": elegiveis,
        "leads_pausados_ignorados": pausados,
        "atualizado_em": cached.get("atualizado_em"),
        "origem": "ops_cache",
    }


def _painel_from_cache(cached: dict[str, Any]) -> dict[str, Any]:
    alertas = []
    for a in cached.get("alertas") or []:
        if isinstance(a, dict):
            alertas.append(a.get("texto") or a.get("log") or str(a))
        else:
            alertas.append(str(a))
    return {
        "totais": cached.get("totais") or {},
        "normalizado": {"saudeGeral": cached.get("saudeGeral")},
        "alertas_api": alertas,
        "saudeGeral": cached.get("saudeGeral"),
        "servicos": cached.get("servicos_problema") or [],
        "servicos_problema": cached.get("servicos_problema") or [],
        "clientes_com_problema": cached.get("clientes_problema") or [],
        "clientes_problema": cached.get("clientes_problema") or [],
        "atualizado_em": cached.get("atualizado_em"),
        "origem": "ops_cache",
    }


async def coletar_tudo(*, forcar_fresco: bool = False) -> dict[str, Any]:
    """Coleta para relatório.

    Preferência: cache vivo (Chatwoot/Hub) + Gestão fresca.
    `forcar_fresco=True` refaz tudo (lento — evitar no scheduler).
    WAHA removido do monitoramento (envio WhatsApp continua em delivery).
    """
    live = ops_cache.get_all()
    async def _gestao():
        try:
            return await asyncio.wait_for(gestao.coletar(), timeout=_GESTAO_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("timeout Gestão (%ss)", _GESTAO_TIMEOUT)
            return resultado_erro("gestao-infinity", f"timeout após {_GESTAO_TIMEOUT:.0f}s")

    async def _painel():
        # Hub: preferir coleta fresca (lista de clientes parcial); cache é fallback.
        try:
            fresh = await asyncio.wait_for(painel.coletar(), timeout=_PAINEL_TIMEOUT)
            if fresh.get("status") == "ok":
                logger.info("painel via coleta fresca")
                return fresh
        except asyncio.TimeoutError:
            logger.warning("timeout Painel fresco (%ss) — tentando cache", _PAINEL_TIMEOUT)
        except Exception:
            logger.exception("Painel fresco falhou — tentando cache")

        cached = live.get("painel")
        if cached and cached.get("status") in ("ok", "erro"):
            logger.info("painel via ops_cache (%s)", cached.get("atualizado_em"))
            st = cached.get("status") or "ok"
            dados = _painel_from_cache(cached)
            if st == "ok":
                return resultado_ok("painel-infinity", dados)
            return resultado_erro("painel-infinity", cached.get("log_geral") or "cache com erro")
        return resultado_erro("painel-infinity", f"timeout/indisponível após {_PAINEL_TIMEOUT:.0f}s")

    async def _chatwoot():
        s = get_settings()
        cached = live.get("chatwoot")
        cache_ok = (
            not forcar_fresco
            and cached
            and cached.get("status") == "ok"
            and snapshot_eh_de_hoje(cached.get("atualizado_em"), tz_name=s.report_timezone)
        )
        if cache_ok:
            logger.info("chatwoot via ops_cache (%s)", cached.get("atualizado_em"))
            return resultado_ok("chatwoot-ias", _chatwoot_from_cache(cached))
        if cached and cached.get("status") == "ok" and not forcar_fresco:
            logger.warning(
                "chatwoot cache fora do dia corrente (%s) — ignorando (só dados de hoje)",
                cached.get("atualizado_em"),
            )
        if not forcar_fresco and cached and cached.get("status") == "erro":
            return resultado_erro("chatwoot-ias", "cache com erro")
        # Sem cache do dia: varredura completa é cara — limita com aviso.
        logger.warning("chatwoot sem cache útil de hoje — varredura completa (pode demorar)")
        try:
            return await asyncio.wait_for(chatwoot_health.coletar(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("timeout Chatwoot (300s)")
            return resultado_erro("chatwoot-ias", "timeout após 300s na varredura")

    gestao_r, painel_r, chatwoot_r = await asyncio.gather(_gestao(), _painel(), _chatwoot())
    return {
        "gestao": gestao_r,
        "painel": painel_r,
        "chatwoot": chatwoot_r,
    }


async def gerar_relatorio_diario(
    *,
    enviar: bool = True,
    forcar: bool = False,
    stamp: str | None = None,
    rotulo: str = "",
    forcar_fresco: bool = False,
) -> dict[str, Any]:
    """Gera o relatório consolidado (manhã/noite ou sob demanda)."""
    s = get_settings()
    if not s.monitor_enabled:
        raise RuntimeError("MONITOR_ENABLED=false")

    logger.info(
        "iniciando coleta (forcar=%s fresco=%s rotulo=%s)",
        forcar,
        forcar_fresco,
        rotulo or "-",
    )
    coletas = await coletar_tudo(forcar_fresco=forcar_fresco)
    snapshot = agregar(coletas)
    if rotulo:
        snapshot["rotulo"] = rotulo

    reprocess_info: dict[str, Any] | None = None
    cw = coletas.get("chatwoot")
    elegiveis: list[dict[str, Any]] = []
    if cw and cw.get("status") == "ok":
        elegiveis = list((cw.get("dados") or {}).get("leads_elegiveis_reprocessamento") or [])
        if elegiveis:
            reprocess_info = await enviar_lote(elegiveis)
        else:
            reprocess_info = {
                "enviados": 0,
                "pulados": 0,
                "status": "vazio",
                "detalhe": "nenhum elegível hoje",
            }
    else:
        reprocess_info = {
            "enviados": 0,
            "pulados": 0,
            "status": "sem_coleta",
            "detalhe": f"chatwoot status={(cw or {}).get('status')}",
        }

    snapshot["reprocessamento"] = {
        **(reprocess_info or {}),
        "automatico_habilitado": bool(s.reprocess_ready),
        "elegiveis_detectados": len(elegiveis),
        "nota": (
            "Reprocess AUTO ligado — lote enviado ao Francisco."
            if s.reprocess_ready
            else "Reprocess AUTO desligado. Detecção ativa; defina REPROCESS_API_TOKEN + REPROCESS_ENABLED=true."
        ),
    }

    from app.agent.graph import sintetizar_relatorio, _fallback_sem_llm

    try:
        relatorio_md = await asyncio.wait_for(
            sintetizar_relatorio(
                snapshot,
                conversation_id=f"relatorio-{stamp or rotulo or 'manual'}",
            ),
            timeout=_LAB_FALLBACK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("timeout síntese LLM (%ss) — fallback estruturado", _LAB_FALLBACK_TIMEOUT)
        relatorio_md = _fallback_sem_llm(snapshot)

    paths = store.salvar(relatorio_md, snapshot, stamp=stamp, rotulo=rotulo)

    pdf_path = None
    try:
        from pathlib import Path

        from app.services.report_pdf import snapshot_para_pdf

        pdf_destino = Path(paths["markdown"]).with_suffix(".pdf")
        # PDF usa layout determinístico (tabelas estáveis). O MD da IA fica no .md / WhatsApp.
        pdf_path = snapshot_para_pdf(snapshot, pdf_destino)
        if pdf_path:
            paths["pdf"] = str(pdf_path)
    except Exception:
        logger.exception("falha ao gerar PDF do relatório")

    enviado = False
    if enviar:
        titulo = "Relatório Infinity Monitor"
        if rotulo == "manha":
            titulo = "Relatório manhã (08h) — Infinity Monitor"
        elif rotulo in ("tarde", "fim_do_dia"):
            titulo = "Relatório noite (20h) — Infinity Monitor"
        enviado = await enviar_whatsapp(relatorio_md, titulo=titulo, pdf_path=pdf_path)

    return {
        "ok": True,
        "relatorio_md": relatorio_md,
        "snapshot": snapshot,
        "paths": paths,
        "enviado_whatsapp": enviado,
        "fontes": snapshot.get("fontes"),
        "alertas": snapshot.get("alertas"),
        "reprocessamento": reprocess_info,
    }
