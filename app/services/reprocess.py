"""Cliente do sistema de reprocessamento do Francisco.

Até o mapeamento de endpoints chegar, o schema de saída já está estável
(montar_payload_reprocess). Quando ele mandar o path/campos reais, ajustamos
só este arquivo + REPROCESS_PATH / env — sem refazer a detecção do Chatwoot.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("monitor.reprocess")


async def enviar_lote(leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Envia só leads elegíveis (pausado=false) ao sistema do Francisco."""
    s = get_settings()
    elegiveis = [l for l in leads if l.get("elegivel_reprocessamento") and not l.get("pausado")]

    if not elegiveis:
        return {"enviados": 0, "pulados": 0, "status": "vazio", "detalhe": "nenhum elegível"}

    if not s.reprocess_ready:
        logger.info(
            "reprocess stub: %d lead(s) prontos, mas REPROCESS_ENABLED/URL off",
            len(elegiveis),
        )
        return {
            "enviados": 0,
            "pulados": len(elegiveis),
            "status": "stub",
            "detalhe": "REPROCESS_ENABLED=false ou REPROCESS_API_BASE_URL vazio",
            "payload_exemplo": elegiveis[0],
            "lote_size": len(elegiveis),
        }

    url = f"{s.reprocess_api_base_url.rstrip('/')}{s.reprocess_path}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if s.reprocess_api_token:
        headers["Authorization"] = f"Bearer {s.reprocess_api_token}"
        headers["X-Reprocess-Token"] = s.reprocess_api_token

    body = {
        "origem": "ia-monitoramento-infinity",
        "motivo": "silencio_ia",
        "leads": elegiveis,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = None
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}
        logger.info("reprocess ok: %d lead(s) → %s", len(elegiveis), url)
        return {
            "enviados": len(elegiveis),
            "pulados": 0,
            "status": "ok",
            "http_status": resp.status_code,
            "resposta": data,
        }
    except Exception as e:
        logger.exception("reprocess falhou")
        return {
            "enviados": 0,
            "pulados": len(elegiveis),
            "status": "erro",
            "detalhe": str(e),
        }
