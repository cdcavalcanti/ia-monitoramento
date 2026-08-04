"""ia-monitoramento-infinity — orquestração.

Fluxo do job diário:

    scheduler/API -> coletores -> aggregator
                  -> LLM (síntese) -> store -> WAHA (opcional)

UI ops: GET /  (dash + chat)
Perguntas: POST /perguntar
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncio

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import alert_poller, chatwoot_poller, metrics, ops_cache, scheduler, store
from app.services.pipeline import gerar_relatorio_diario
from app.services.reprocess import enviar_lote
from app.services.scheduler import horarios_relatorio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("monitor")

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_started_at = datetime.now(timezone.utc)
_auth_probe_cache: dict[str, Any] = {"ts": 0.0, "data": None}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings.ensure_dirs()
    metrics.init()
    ops_cache.load_disk()
    metrics.heartbeat("app", "starting", {"pid": "main"})
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
    metrics.heartbeat("app", "ok", {"uptime_from": _started_at.isoformat()})

    async def _warm_cache() -> None:
        try:
            from app.collectors.painel import coletar_overview_leve

            if settings.painel_enabled:
                pr = await coletar_overview_leve()
                if pr["status"] == "ok":
                    ops_cache.set_painel(pr["dados"] or {}, status="ok")
        except Exception:
            logger.exception("warm cache falhou")

    asyncio.create_task(_warm_cache(), name="ops-warm-cache")
    yield
    await alert_poller.stop()
    await chatwoot_poller.stop()
    await scheduler.stop()
    metrics.heartbeat("app", "stopped")


app = FastAPI(title="ia-monitoramento-infinity", lifespan=_lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def ui_home() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "UI não encontrada (static/index.html)")
    return FileResponse(index)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "monitor_enabled": settings.monitor_enabled,
        "modelo": settings.openai_chat_model,
        "infinity_lab": settings.infinity_lab_enabled,
        "infinity_lab_agent": settings.infinity_lab_agent_id or None,
        "gestao": settings.gestao_enabled,
        "painel": settings.painel_enabled,
        "chatwoot_health": settings.chatwoot_health_enabled,
        "chatwoot_silence_min": settings.chatwoot_silence_minutes,
        "chatwoot_only_today": settings.chatwoot_only_today,
        "chatwoot_contas": len(settings.chatwoot_account_list),
        "waha_health": False,
        "alert_poller": settings.alert_poller_enabled,
        "reprocess": settings.reprocess_ready,
        "scheduler": settings.scheduler_enabled,
        "report_slots": [f"{h:02d}:{m:02d}" for h, m in horarios_relatorio()],
        "report_at": f"{settings.report_hour:02d}:{settings.report_minute:02d} {settings.report_timezone}",
        "whatsapp_delivery": settings.delivery_whatsapp_enabled,
        "started_at": _started_at.isoformat(),
    }


@app.get("/ops/status")
async def ops_status() -> dict[str, Any]:
    """Status operacional para o dash (fontes + uptime + último relatório)."""
    ultimo = store.carregar_ultimo() or {}
    snap = ultimo.get("snapshot") or {}
    contas = settings.chatwoot_account_list
    return {
        "ok": True,
        "uptime_desde": _started_at.isoformat(),
        "agora": datetime.now(timezone.utc).isoformat(),
        "operando": bool(settings.monitor_enabled and settings.scheduler_enabled),
        "fontes": {
            "gestao": settings.gestao_enabled,
            "painel": settings.painel_enabled,
            "chatwoot": settings.chatwoot_health_enabled,
            "lab": settings.infinity_lab_enabled,
            "openai_fallback": bool(settings.openai_api_key),
            "whatsapp": settings.delivery_whatsapp_enabled,
            "reprocess_auto": settings.reprocess_ready,
        },
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "slots": [f"{h:02d}:{m:02d}" for h, m in horarios_relatorio()],
            "timezone": settings.report_timezone,
        },
        "chatwoot": {
            "silence_min": settings.chatwoot_silence_minutes,
            "only_today": settings.chatwoot_only_today,
            "contas": len(contas),
            "contas_com_inbox": sum(1 for c in contas if c.get("inbox_ids")),
            "poll_seconds": settings.chatwoot_poll_seconds,
        },
        "ultimo_relatorio": {
            "salvo_em": ultimo.get("salvo_em"),
            "stamp": ultimo.get("stamp"),
            "rotulo": ultimo.get("rotulo"),
            "alertas": (snap.get("alertas") or [])[:12],
            "fontes_snap": snap.get("fontes"),
        },
    }


@app.get("/ops/metrics")
async def ops_metrics() -> dict[str, Any]:
    return metrics.snapshot()


_last_auth_probe: dict[str, Any] | None = None
_last_auth_probe_ts: float = 0.0


@app.get("/ops/reprocess")
async def ops_reprocess(light: bool = False) -> dict[str, Any]:
    """Painel do sistema de reprocessamento (estado + fila local + último lote).

    light=1 → só dados locais (rápido para o dash); sem health/auth externos.
    """
    import time

    from app.config import get_settings as _gs

    global _last_auth_probe, _last_auth_probe_ts

    s = _gs()
    snap = metrics.snapshot()
    endpoint = f"{(s.reprocess_api_base_url or '').rstrip('/')}{s.reprocess_path}"
    health: dict[str, Any] | None = None
    auth_probe: dict[str, Any] | None = _last_auth_probe
    token_ok = bool(s.reprocess_api_token)

    if not light and s.reprocess_api_base_url:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{s.reprocess_api_base_url.rstrip('/')}/health")
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text[:200]}
                health = {"http_status": resp.status_code, "ok": resp.status_code == 200, "body": body}
        except Exception as e:
            health = {"ok": False, "erro": str(e)[:240]}

    agora = time.monotonic()
    if not light and s.reprocess_ready and token_ok:
        if _last_auth_probe and (agora - _last_auth_probe_ts) < 120:
            auth_probe = _last_auth_probe
        else:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    probe = await client.post(
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {s.reprocess_api_token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json={
                            "origem": "ia-monitoramento-infinity",
                            "motivo": "silencio_ia",
                            "leads": [],
                        },
                    )
                auth_probe = {
                    "http_status": probe.status_code,
                    "ok": probe.status_code in (400, 202, 200) and probe.status_code != 401,
                    "unauthorized": probe.status_code == 401,
                }
                try:
                    auth_probe["body"] = probe.json()
                except Exception:
                    auth_probe["body"] = {"raw": probe.text[:200]}
                _last_auth_probe = auth_probe
                _last_auth_probe_ts = agora
            except Exception as e:
                auth_probe = {"ok": False, "erro": str(e)[:240]}
                _last_auth_probe = auth_probe
                _last_auth_probe_ts = agora

    if not s.reprocess_ready:
        modo = "desligado"
    elif not token_ok:
        modo = "sem_token"
    elif auth_probe and auth_probe.get("unauthorized"):
        modo = "token_invalido"
    elif auth_probe and auth_probe.get("ok") is False and "erro" in (auth_probe or {}):
        modo = "api_indisponivel"
    elif s.reprocess_ready and token_ok:
        modo = "ativo"
    else:
        modo = "desligado"

    return {
        "ok": True,
        "modo": modo,
        "config": {
            "enabled": bool(s.reprocess_enabled),
            "ready": bool(s.reprocess_ready),
            "token_configurado": token_ok,
            "base_url": s.reprocess_api_base_url or None,
            "path": s.reprocess_path,
            "endpoint": endpoint,
            "max_batch": s.reprocess_max_batch_size,
            "origem": "ia-monitoramento-infinity",
            "poll_seconds": s.chatwoot_poll_seconds,
        },
        "health": health,
        "auth_probe": auth_probe,
        "hoje": snap.get("reprocess_hoje") or {},
        "eventos": snap.get("reprocess_recentes") or [],
        "enviados": snap.get("reprocess_enviados") or [],
        "ultimo_lote": snap.get("reprocess_ultimo_lote"),
        "dia": snap.get("dia"),
    }


@app.get("/ops/live")
async def ops_live() -> dict[str, Any]:
    """Snapshots cacheados: Chatwoot (leads) + Hub (problemas)."""
    return {
        "ok": True,
        "agora": datetime.now(timezone.utc).isoformat(),
        "poll_hint": {
            "ui_seconds": 8,
            "hub_seconds": settings.alert_poll_seconds,
            "chatwoot_seconds": settings.chatwoot_poll_seconds,
        },
        **ops_cache.get_all(),
    }


_last_light_refresh: float = 0.0
_light_lock: asyncio.Lock | None = None


def _get_light_lock() -> asyncio.Lock:
    global _light_lock
    if _light_lock is None:
        _light_lock = asyncio.Lock()
    return _light_lock


@app.post("/ops/refresh-live")
async def ops_refresh_live() -> dict[str, Any]:
    """Atualiza Hub agora (leve). Debounce ~15s pra não martelar APIs."""
    import time

    global _last_light_refresh
    async with _get_light_lock():
        agora = time.monotonic()
        skipped = agora - _last_light_refresh < 15.0
        if not skipped:
            _last_light_refresh = agora
            try:
                from app.collectors.painel import coletar_overview_leve

                if settings.painel_enabled:
                    pr = await coletar_overview_leve()
                    if pr["status"] == "ok":
                        ops_cache.set_painel(pr["dados"] or {}, status="ok")
            except Exception as e:
                logger.exception("refresh-live falhou")
                raise HTTPException(500, str(e)) from e

    return {
        "ok": True,
        "refreshed": not skipped,
        "skipped_debounce": skipped,
        **ops_cache.get_all(),
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
    from app.collectors import chatwoot_health

    resultado = await chatwoot_health.coletar()
    dados = resultado.get("dados") or {}
    elegiveis = list(dados.get("leads_elegiveis_reprocessamento") or [])
    if resultado["status"] == "ok":
        ops_cache.set_chatwoot(dados, status="ok")
    if resultado["status"] == "ok" and elegiveis:
        metrics.record_reprocess(
            kind="captured",
            count=len(elegiveis),
            status="api_manual",
            detail="GET /chatwoot/leads-silencio",
        )
    return {
        "status": resultado["status"],
        "fonte": resultado["fonte"],
        "coletado_em": resultado["coletado_em"],
        "dados": dados,
    }


class ReprocessBody(BaseModel):
    enviar: bool = Field(True, description="Se false, só lista elegíveis sem POST no Francisco")
    force: bool = Field(
        False,
        description="Se true, ignora dedup local do dia (ainda respeita idempotência do Francisco)",
    )


@app.post("/chatwoot/reprocessar")
async def chatwoot_reprocessar(body: ReprocessBody | None = None) -> dict[str, Any]:
    from app.collectors import chatwoot_health

    body = body or ReprocessBody()
    resultado = await chatwoot_health.coletar()
    if resultado["status"] != "ok":
        raise HTTPException(502, f"coleta chatwoot: {resultado['status']} — {resultado.get('dados')}")

    elegiveis = list((resultado["dados"] or {}).get("leads_elegiveis_reprocessamento") or [])
    if elegiveis:
        metrics.record_reprocess(
            kind="captured",
            count=len(elegiveis),
            status="api_manual",
            detail="POST /chatwoot/reprocessar",
        )
    envio = None
    if body.enviar:
        envio = await enviar_lote(elegiveis, force=bool(body.force))
    return {
        "totais": (resultado["dados"] or {}).get("totais"),
        "elegiveis": elegiveis,
        "pausados": (resultado["dados"] or {}).get("leads_pausados_ignorados") or [],
        "reprocessamento": envio,
        "automatico_habilitado": bool(settings.reprocess_ready),
    }


class PerguntarBody(BaseModel):
    pergunta: str
    thread_id: str = "ops-ui"


@app.get("/chatwoot/reprocessar/status")
async def chatwoot_reprocessar_status(
    queue_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Consulta item na fila do Francisco (queue_id ou request_id)."""
    from app.services.reprocess import consultar_status

    if not queue_id and not request_id:
        raise HTTPException(400, "Informe queue_id ou request_id")
    return await consultar_status(queue_id=queue_id, request_id=request_id)


@app.post("/perguntar")
async def perguntar(body: PerguntarBody) -> dict[str, str]:
    if not settings.openai_api_key and not settings.infinity_lab_enabled:
        raise HTTPException(503, "configure Infinity Lab ou OPENAI_API_KEY")
    from app.agent.graph import perguntar as agent_perguntar

    try:
        resposta = await agent_perguntar(body.thread_id, body.pergunta)
    except Exception as e:
        logger.exception("perguntar falhou")
        raise HTTPException(500, str(e)) from e
    return {"resposta": resposta}
