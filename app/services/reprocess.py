"""Cliente do sistema de reprocessamento (Francisco / chat-reprocessor).

Contrato oficial (doc 03/08/2026):
  POST {BASE}/api/reprocess/automatic
  Auth: Authorization: Bearer <REPROCESS_API_TOKEN>  (ou X-Reprocess-Token)
  Body: { origem: "ia-monitoramento-infinity", motivo: "silencio_ia", leads: [...] }
  Sucesso: HTTP 202 + { ok, aceitos, ignorados, erros, resultados[] }
  Limite: 1–20 leads por lote (chunk automático aqui)

Idempotência: calculada pelo Francisco (origem+conta+conversa+última msg).
Dedup local por dia evita spam do poller.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services import metrics
from app.services.tempo import hoje_iso

logger = logging.getLogger("monitor.reprocess")

ORIGEM = "ia-monitoramento-infinity"
MOTIVO_DEFAULT = "silencio_ia"


def _max_batch() -> int:
    try:
        n = int(get_settings().reprocess_max_batch_size or 20)
    except Exception:
        n = 20
    return max(1, min(n, 20))


def _lead_key(lead: dict[str, Any]) -> str | None:
    account = lead.get("account_id")
    conv = lead.get("conversation_id")
    if account is None or conv is None:
        return None
    return f"{account}:{conv}:{hoje_iso()}"


def _filtrar_elegiveis(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [l for l in leads if l.get("elegivel_reprocessamento") and not l.get("pausado")]


def _chunks(items: list[dict[str, Any]], size: int | None = None) -> list[list[dict[str, Any]]]:
    n = size if size is not None else _max_batch()
    return [items[i : i + n] for i in range(0, len(items), n)]


def _marcar_dedup_dos_resultados(
    novos: list[dict[str, Any]],
    resultados: list[Any],
    *,
    aceitos: int,
    http_ok: bool,
) -> None:
    for item in resultados:
        if not isinstance(item, dict):
            continue
        st = str(item.get("status") or "")
        motivo = str(item.get("motivo") or "")
        if st == "enfileirado" or (st == "ignorado" and motivo == "ja_processado"):
            cid = item.get("conversation_id")
            account = None
            for lead in novos:
                if str(lead.get("conversation_id")) == str(cid):
                    account = lead.get("account_id")
                    break
            if account is None or cid is None:
                continue
            metrics.marcar_enviado_reprocess(
                f"{account}:{cid}:{hoje_iso()}",
                status=st,
                detail=motivo or st,
                queue_id=str(item.get("queue_id") or "") or None,
            )
    if not resultados and aceitos > 0 and http_ok:
        for lead in novos:
            key = _lead_key(lead)
            if key:
                metrics.marcar_enviado_reprocess(key, status="enfileirado", detail="lote_ok")


async def _post_lote(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    leads: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "origem": ORIGEM,
        "motivo": MOTIVO_DEFAULT,
        "leads": leads,
    }
    resp = await client.post(url, headers=headers, json=body)
    if resp.status_code not in (200, 202):
        # tenta extrair mensagem da API
        detalhe = resp.text[:400]
        try:
            err = resp.json()
            detalhe = str(err.get("mensagem") or err.get("erro") or detalhe)
        except Exception:
            pass
        if resp.status_code == 401:
            detalhe = (
                "Token rejeitado pelo Francisco (HTTP 401). "
                "Confirme se é o REPROCESS_API_TOKEN (não o WORKER). "
                f"Detalhe: {detalhe}"
            )
        raise httpx.HTTPStatusError(
            f"HTTP {resp.status_code}: {detalhe}",
            request=resp.request,
            response=resp,
        )
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if not isinstance(data, dict):
        data = {"raw": data}
    data["_http_status"] = resp.status_code
    return data


async def consultar_status(
    *,
    queue_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """GET /api/reprocess/automatic/status?queue_id=…|request_id=…"""
    s = get_settings()
    if not (queue_id or request_id):
        return {"ok": False, "erro": "identifier_required", "mensagem": "Informe queue_id ou request_id."}
    if not s.reprocess_api_base_url or not s.reprocess_api_token:
        return {"ok": False, "erro": "not_configured", "mensagem": "REPROCESS_* incompleto."}

    params: dict[str, str] = {}
    if queue_id:
        params["queue_id"] = str(queue_id)
    if request_id:
        params["request_id"] = str(request_id)

    url = f"{s.reprocess_api_base_url.rstrip('/')}/api/reprocess/automatic/status"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {s.reprocess_api_token}",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:400]}
        if resp.status_code >= 400:
            return {
                "ok": False,
                "http_status": resp.status_code,
                **(data if isinstance(data, dict) else {"resposta": data}),
            }
        return data if isinstance(data, dict) else {"ok": True, "resposta": data}


async def enviar_lote(
    leads: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Envia só leads elegíveis (pausado=false) ao chat-reprocessor (chunks ≤20)."""
    s = get_settings()
    elegiveis = _filtrar_elegiveis(leads)

    if not elegiveis:
        return {"enviados": 0, "pulados": 0, "status": "vazio", "detalhe": "nenhum elegível"}

    endpoint = f"{(s.reprocess_api_base_url or '').rstrip('/')}{s.reprocess_path}"

    if not s.reprocess_ready:
        logger.info(
            "reprocess stub: %d lead(s) prontos, mas REPROCESS_ENABLED/URL off",
            len(elegiveis),
        )
        metrics.record_reprocess(
            kind="stub",
            count=len(elegiveis),
            status="stub",
            detail="REPROCESS_ENABLED=false ou URL vazia",
        )
        return {
            "enviados": 0,
            "pulados": len(elegiveis),
            "status": "stub",
            "detalhe": "REPROCESS_ENABLED=false ou REPROCESS_API_BASE_URL vazio",
            "payload_exemplo": elegiveis[0],
            "lote_size": len(elegiveis),
            "endpoint": endpoint,
        }

    if not s.reprocess_api_token:
        metrics.record_reprocess(
            kind="erro",
            count=len(elegiveis),
            status="sem_token",
            detail="REPROCESS_API_TOKEN vazio",
        )
        return {
            "enviados": 0,
            "pulados": len(elegiveis),
            "status": "erro",
            "detalhe": "REPROCESS_API_TOKEN vazio — cole o token do chat-reprocessor",
            "endpoint": endpoint,
        }

    novos: list[dict[str, Any]] = []
    pulados_dedup: list[dict[str, Any]] = []
    if force:
        novos = list(elegiveis)
    else:
        for lead in elegiveis:
            key = _lead_key(lead)
            if key and metrics.ja_enviado_reprocess(key):
                pulados_dedup.append(
                    {
                        "conversation_id": lead.get("conversation_id"),
                        "account_id": lead.get("account_id"),
                        "motivo": "dedup_local_hoje",
                    }
                )
            else:
                novos.append(lead)

    if not novos:
        metrics.record_reprocess(
            kind="stub",
            count=len(pulados_dedup),
            status="dedup",
            detail="todos já enfileirados hoje (dedup local)",
        )
        return {
            "enviados": 0,
            "pulados": len(pulados_dedup),
            "status": "dedup",
            "detalhe": "nenhum lead novo — todos já enviados hoje",
            "pulados_dedup": pulados_dedup[:40],
            "endpoint": endpoint,
        }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {s.reprocess_api_token}",
    }

    lotes = _chunks(novos)
    total_aceitos = 0
    total_ignorados = 0
    total_erros = 0
    todos_resultados: list[Any] = []
    http_status = None
    ultima_resposta: dict[str, Any] | None = None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for i, lote in enumerate(lotes):
                data = await _post_lote(client, url=endpoint, headers=headers, leads=lote)
                http_status = data.pop("_http_status", 202)
                ultima_resposta = data
                aceitos = int(data.get("aceitos") or 0)
                ignorados = int(data.get("ignorados") or 0)
                erros = int(data.get("erros") or 0)
                resultados = list(data.get("resultados") or [])
                total_aceitos += aceitos
                total_ignorados += ignorados
                total_erros += erros
                todos_resultados.extend(resultados)
                _marcar_dedup_dos_resultados(
                    lote, resultados, aceitos=aceitos, http_ok=http_status in (200, 202)
                )
                logger.info(
                    "reprocess lote %s/%s: http=%s aceitos=%s ignorados=%s erros=%s",
                    i + 1,
                    len(lotes),
                    http_status,
                    aceitos,
                    ignorados,
                    erros,
                )
    except Exception as e:
        logger.exception("reprocess falhou")
        metrics.record_reprocess(
            kind="erro",
            count=len(novos),
            status="erro",
            detail=str(e)[:400],
        )
        return {
            "enviados": total_aceitos,
            "pulados": len(pulados_dedup) + total_ignorados,
            "status": "erro",
            "detalhe": str(e),
            "endpoint": endpoint,
            "aceitos": total_aceitos,
            "ignorados": total_ignorados,
            "erros": total_erros,
            "resultados": todos_resultados[:80],
            "pulados_dedup": pulados_dedup[:40],
            "lotes": len(lotes),
        }

    metrics.record_reprocess(
        kind="sent",
        count=total_aceitos or len(novos),
        status="ok",
        detail=(
            f"http={http_status} aceitos={total_aceitos} "
            f"ignorados={total_ignorados} erros={total_erros} lotes={len(lotes)}"
        ),
    )
    out = {
        "enviados": total_aceitos,
        "pulados": len(pulados_dedup) + total_ignorados,
        "status": "ok",
        "http_status": http_status,
        "aceitos": total_aceitos,
        "ignorados": total_ignorados,
        "erros": total_erros,
        "resultados": todos_resultados[:80],
        "resposta": ultima_resposta,
        "endpoint": endpoint,
        "pulados_dedup": pulados_dedup[:40],
        "lotes": len(lotes),
        "queue_ids": [
            r.get("queue_id")
            for r in todos_resultados
            if isinstance(r, dict) and r.get("status") == "enfileirado" and r.get("queue_id")
        ],
    }
    try:
        metrics.salvar_lote_reprocess(out)
    except Exception:
        logger.exception("falha ao salvar lote reprocess no painel")
    return out
