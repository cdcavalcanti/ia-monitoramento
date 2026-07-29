"""Pipeline: coletar → agregar → sintetizar (LLM) → salvar → entregar."""

from __future__ import annotations

import logging
from typing import Any

from app.collectors import chatwoot_health, gestao, painel, waha_health
from app.config import get_settings
from app.services import store
from app.services.aggregator import agregar
from app.services.delivery import enviar_whatsapp
from app.services.reprocess import enviar_lote

logger = logging.getLogger("monitor.pipeline")


async def coletar_tudo() -> dict[str, Any]:
    gestao_r = await gestao.coletar()
    painel_r = await painel.coletar()
    chatwoot_r = await chatwoot_health.coletar()
    waha_r = await waha_health.coletar()
    return {
        "gestao": gestao_r,
        "painel": painel_r,
        "chatwoot": chatwoot_r,
        "waha": waha_r,
    }


async def gerar_relatorio_diario(
    *,
    enviar: bool = True,
    forcar: bool = False,
    stamp: str | None = None,
    rotulo: str = "",
) -> dict[str, Any]:
    """Gera o relatório consolidado (manhã/tarde ou sob demanda)."""
    s = get_settings()
    if not s.monitor_enabled:
        raise RuntimeError("MONITOR_ENABLED=false")

    logger.info("iniciando coleta (forcar=%s rotulo=%s)", forcar, rotulo or "-")
    coletas = await coletar_tudo()
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
            else "Reprocess AUTO desligado (REPROCESS_ENABLED=false). Detecção ativa; envio só quando Francisco plugar."
        ),
    }

    from app.agent.graph import sintetizar_relatorio

    relatorio_md = await sintetizar_relatorio(
        snapshot,
        conversation_id=f"relatorio-{stamp or rotulo or 'manual'}",
    )
    paths = store.salvar(relatorio_md, snapshot, stamp=stamp, rotulo=rotulo)

    enviado = False
    if enviar:
        titulo = "Relatório Infinity Monitor"
        if rotulo == "manha":
            titulo = "Relatório manhã (08h) — Infinity Monitor"
        elif rotulo in ("tarde", "fim_do_dia"):
            titulo = "Relatório noite (20h) — Infinity Monitor"
        enviado = await enviar_whatsapp(relatorio_md, titulo=titulo)

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
