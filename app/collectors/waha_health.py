"""Saúde das sessões WAHA (instâncias WhatsApp).

Endpoints típicos do WAHA:
  GET /api/sessions
  GET /api/sessions/{name}

Status comuns: WORKING, STOPPED, FAILED, SCAN_QR_CODE, STARTING…
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok, resultado_stub
from app.config import get_settings

logger = logging.getLogger("monitor.waha")

FONTE = "waha-sessoes"

# Considerados "ruins" para alerta de transição.
STATUS_RUINS = {"FAILED", "STOPPED", "SCAN_QR_CODE", "BROKEN"}


class WahaClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        # WAHA usa X-Api-Key (Bearer sozinho retorna 401 neste cluster).
        return {
            "Accept": "application/json",
            "X-Api-Key": self.token,
            "Authorization": f"Bearer {self.token}",
        }

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def listar_sessoes(self) -> Any:
        return await self._get("/api/sessions")


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "sessions", "result"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        # às vezes é mapa nome→obj
        vals = [v for v in payload.values() if isinstance(v, dict) and ("name" in v or "status" in v)]
        if vals:
            return vals
    return []


def normalizar_sessoes(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in _as_list(payload):
        nome = str(s.get("name") or s.get("session") or s.get("id") or "?")
        status = str(s.get("status") or s.get("state") or "UNKNOWN").upper()
        out.append(
            {
                "name": nome,
                "status": status,
                "ok": status == "WORKING",
                "ruim": status in STATUS_RUINS,
                "raw": {k: s.get(k) for k in ("engine", "me", "config") if k in s},
            }
        )
    out.sort(key=lambda x: x["name"])
    return out


async def coletar() -> ColetaResult:
    s = get_settings()
    if not s.waha_health_enabled:
        return resultado_stub(
            FONTE,
            "Monitoramento de sessões WAHA desligado (WAHA_HEALTH_ENABLED=false).",
        )
    if not (s.waha_url and s.waha_token):
        return resultado_erro(FONTE, "WAHA_HEALTH_ENABLED=true mas WAHA_URL/TOKEN ausentes")

    client = WahaClient(s.waha_url, s.waha_token)
    try:
        raw = await client.listar_sessoes()
        sessoes = normalizar_sessoes(raw)
        ruins = [x for x in sessoes if x["ruim"]]
        ok = [x for x in sessoes if x["ok"]]
        return resultado_ok(
            FONTE,
            {
                "sessoes": sessoes,
                "totais": {
                    "total": len(sessoes),
                    "working": len(ok),
                    "ruins": len(ruins),
                },
                "ruins": ruins,
            },
        )
    except Exception as e:
        logger.exception("waha health falhou")
        return resultado_erro(FONTE, str(e))
