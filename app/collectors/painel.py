"""Collector do Painel de Serviços (painel-infinity) — FASE 2.

Quando a API chegar, preencher:
  GET /api/status/overview
  GET /api/clientes
  GET /api/clientes/:id/servicos
  (e demais endpoints do doc que a equipe enviar)

Até lá o relatório marca esta fonte como pendente, sem inventar status.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok, resultado_stub
from app.config import get_settings

logger = logging.getLogger("monitor.painel")

FONTE = "painel-infinity"


class PainelClient:
    def __init__(self, base_url: str, token: str, timeout: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            # Placeholder: ajustar o header real quando a API for documentada.
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-Relatorio-Token"] = self.token
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def overview(self) -> Any:
        return await self._get("/api/status/overview")

    async def listar_clientes(self) -> Any:
        return await self._get("/api/clientes")


async def coletar() -> ColetaResult:
    s = get_settings()
    if not s.painel_enabled:
        return resultado_stub(
            FONTE,
            "Painel de Serviços ainda não conectado (PAINEL_ENABLED=false). "
            "Aguardando documentação/API da equipe.",
        )

    if not s.painel_api_base_url:
        return resultado_erro(FONTE, "PAINEL_ENABLED=true mas PAINEL_API_BASE_URL vazio")

    client = PainelClient(s.painel_api_base_url, s.painel_api_token)
    try:
        overview = await client.overview()
        clientes = await client.listar_clientes()
        return resultado_ok(
            FONTE,
            {
                "overview": overview,
                "clientes": clientes,
            },
        )
    except Exception as e:
        logger.exception("painel falhou")
        return resultado_erro(FONTE, str(e))
