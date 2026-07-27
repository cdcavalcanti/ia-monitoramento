"""ia-monitoramento-infinity — orquestração.

Fluxo do job diário:

    scheduler/API -> coletores (gestao + stubs) -> aggregator
                  -> LLM (síntese) -> store -> WAHA (opcional)

Perguntas pontuais: POST /perguntar usa o agente ReAct com tools sobre o
último relatório.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import alert_poller, chatwoot_poller, scheduler, store
from app.services.pipeline import gerar_relatorio_diario
from app.services.reprocess import enviar_lote
from app.services.scheduler import horarios_relatorio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("monitor")

settings = get_settings()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings.ensure_dirs()
    logger.info("modelo=%s", settings.openai_chat_model)
    logger.info("gestao=%s", "ok" if settings.gestao_enabled else "SEM TOKEN")
    logger.info("painel_enabled=%s chatwoot_health=%s", settings.painel_enabled, settings.chatwoot_health_enabled)
    logger.info(
        "scheduler=%s slots=%s %s",
        settings.scheduler_enabled,
        ", ".join(f"{h:02d}:{m:02d}" for h, m in horarios_relatorio()),
        settings.report_timezone,
    )
    await scheduler.start()
    await chatwoot_poller.start()
    await alert_poller.start()
    yield
    await alert_poller.stop()
    await chatwoot_poller.stop()
    await scheduler.stop()


app = FastAPI(title="ia-monitoramento-infinity", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "monitor_enabled": settings.monitor_enabled,
        "modelo": settings.openai_chat_model,
        "gestao": settings.gestao_enabled,
        "painel": settings.painel_enabled,
        "chatwoot_health": settings.chatwoot_health_enabled,
        "chatwoot_silence_min": settings.chatwoot_silence_minutes,
        "waha_health": settings.waha_health_enabled,
        "alert_poller": settings.alert_poller_enabled,
        "reprocess": settings.reprocess_ready,
        "scheduler": settings.scheduler_enabled,
        "report_slots": [f"{h:02d}:{m:02d}" for h, m in horarios_relatorio()],
        "report_at": f"{settings.report_hour:02d}:{settings.report_minute:02d} {settings.report_timezone}",
        "whatsapp_delivery": settings.delivery_whatsapp_enabled,
    }


class GerarBody(BaseModel):
    enviar: bool = Field(True, description="Envia resumo via WAHA se configurado")
    forcar: bool = Field(True, description="Regenera mesmo se já existir relatório do dia")


@app.post("/relatorio/gerar")
async def relatorio_gerar(body: GerarBody | None = None) -> dict[str, Any]:
    if not settings.monitor_enabled:
        raise HTTPException(503, "MONITOR_ENABLED=false")
    body = body or GerarBody()
    try:
        resultado = await gerar_relatorio_diario(enviar=body.enviar, forcar=body.forcar)
    except Exception as e:
        logger.exception("falha ao gerar relatório")
        raise HTTPException(500, str(e)) from e

    # Não devolve o snapshot inteiro na API por padrão (pode ser enorme).
    return {
        "ok": True,
        "paths": resultado["paths"],
        "enviado_whatsapp": resultado["enviado_whatsapp"],
        "fontes": resultado["fontes"],
        "alertas": resultado["alertas"],
        "reprocessamento": resultado.get("reprocessamento"),
        "relatorio_md": resultado["relatorio_md"],
    }


@app.get("/relatorio/ultimo")
async def relatorio_ultimo() -> dict[str, Any]:
    dados = store.carregar_ultimo()
    if not dados:
        raise HTTPException(404, "nenhum relatório gerado ainda")
    return {
        "salvo_em": dados.get("salvo_em"),
        "relatorio_md": dados.get("relatorio_md"),
        "fontes": (dados.get("snapshot") or {}).get("fontes"),
        "alertas": (dados.get("snapshot") or {}).get("alertas"),
    }


@app.get("/chatwoot/leads-silencio")
async def chatwoot_leads_silencio() -> dict[str, Any]:
    """Varre agora: leads >N min sem resposta, separados por elegível/pausado."""
    from app.collectors import chatwoot_health

    resultado = await chatwoot_health.coletar()
    return {
        "status": resultado["status"],
        "fonte": resultado["fonte"],
        "coletado_em": resultado["coletado_em"],
        "dados": resultado["dados"],
    }


class ReprocessBody(BaseModel):
    enviar: bool = Field(True, description="Se false, só lista elegíveis sem POST no Francisco")


@app.post("/chatwoot/reprocessar")
async def chatwoot_reprocessar(body: ReprocessBody | None = None) -> dict[str, Any]:
    """Detecta silêncios e (opcionalmente) dispara o lote no sistema do Francisco."""
    from app.collectors import chatwoot_health

    body = body or ReprocessBody()
    resultado = await chatwoot_health.coletar()
    if resultado["status"] != "ok":
        raise HTTPException(502, f"coleta chatwoot: {resultado['status']} — {resultado.get('dados')}")

    elegiveis = list((resultado["dados"] or {}).get("leads_elegiveis_reprocessamento") or [])
    envio = None
    if body.enviar:
        envio = await enviar_lote(elegiveis)
    return {
        "totais": (resultado["dados"] or {}).get("totais"),
        "elegiveis": elegiveis,
        "pausados": (resultado["dados"] or {}).get("leads_pausados_ignorados") or [],
        "reprocessamento": envio,
    }


class PerguntarBody(BaseModel):
    pergunta: str
    thread_id: str = "ops"


@app.post("/perguntar")
async def perguntar(body: PerguntarBody) -> dict[str, str]:
    if not settings.openai_api_key:
        raise HTTPException(503, "OPENAI_API_KEY ausente")
    from app.agent.graph import perguntar as agent_perguntar

    try:
        resposta = await agent_perguntar(body.thread_id, body.pergunta)
    except Exception as e:
        logger.exception("perguntar falhou")
        raise HTTPException(500, str(e)) from e
    return {"resposta": resposta}
