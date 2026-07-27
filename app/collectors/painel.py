"""Collector do Hub de Status Infinity (painel-infinity).

Docs: https://painel-infinity.vercel.app/api/docs
OpenAPI: GET /api/openapi

Auth:
  - HTTP Basic (login do painel) — PAINEL_API_USER + PAINEL_API_PASSWORD
  - ou Bearer — Authorization: Bearer <PAINEL_API_TOKEN>

Endpoints:
  GET /api/status/overview          — leve, ideal pro poller de alertas
  GET /api/clientes
  GET /api/clientes/{id}/servicos
  GET /api/clientes/{id}/webhooks
  GET /api/clientes/{id}/custo
  GET /api/relatorio-diario         — agregador (~20–40s cold start)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok, resultado_stub
from app.config import get_settings

logger = logging.getLogger("monitor.painel")

FONTE = "painel-infinity"

# Enums estáveis da API
HEALTH_RUIM = {"partial", "offline"}
UPDOWN_RUIM = {"offline", "degraded"}


class PainelClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str = "",
        password: str = "",
        bearer_token: str = "",
        timeout: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.bearer_token = bearer_token
        self.timeout = timeout

    def _auth(self) -> httpx.Auth | None:
        if self.username:
            return httpx.BasicAuth(self.username, self.password)
        return None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if not self.username and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, auth=self._auth()) as client:
            resp = await client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def overview(self) -> Any:
        return await self._get("/api/status/overview")

    async def listar_clientes(self) -> Any:
        return await self._get("/api/clientes")

    async def servicos_cliente(self, cliente_id: str) -> Any:
        return await self._get(f"/api/clientes/{cliente_id}/servicos")

    async def webhooks_cliente(self, cliente_id: str) -> Any:
        return await self._get(f"/api/clientes/{cliente_id}/webhooks")

    async def custo_cliente(self, cliente_id: str) -> Any:
        return await self._get(f"/api/clientes/{cliente_id}/custo")

    async def relatorio_diario(self) -> Any:
        return await self._get("/api/relatorio-diario")


def _credenciais() -> tuple[str, str, str]:
    s = get_settings()
    user = (s.painel_api_user or "").strip()
    password = (s.painel_api_password or "").strip()
    token = (s.painel_api_token or "").strip()
    basic = (s.painel_basic_auth or "").strip()
    if basic and ":" in basic and not user:
        user, password = basic.split(":", 1)
    return user, password, token


def _client() -> PainelClient:
    s = get_settings()
    user, password, token = _credenciais()
    return PainelClient(
        s.painel_api_base_url or "https://painel-infinity.vercel.app",
        username=user,
        password=password,
        bearer_token=token,
    )


def normalizar_overview(overview: dict[str, Any]) -> dict[str, Any]:
    """Extrai listas acionáveis p/ relatório e alertas."""
    servicos_http = list(overview.get("servicos") or [])
    falhas = list(overview.get("servicosComFalha") or [])
    if not falhas:
        falhas = [s for s in servicos_http if str(s.get("status") or "").lower() in UPDOWN_RUIM]

    itens_alerta: list[dict[str, Any]] = []
    for s in falhas:
        if not isinstance(s, dict):
            continue
        st = str(s.get("status") or "offline").lower()
        itens_alerta.append(
            {
                "tipo": "servico_http",
                "nome": s.get("name") or "?",
                "cliente": "",
                "status": st,
                "nivel": "ruim" if st in UPDOWN_RUIM else "ok",
                "url": s.get("url") or "",
            }
        )

    numeros = overview.get("numeros") or {}
    if isinstance(numeros, dict) and numeros.get("pendente") is not True:
        for sess in numeros.get("sessoes") or []:
            if not isinstance(sess, dict):
                continue
            conectado = bool(sess.get("conectado"))
            st = str(sess.get("status") or ("WORKING" if conectado else "STOPPED"))
            if conectado and st.upper() == "WORKING":
                continue
            itens_alerta.append(
                {
                    "tipo": "waha_numero",
                    "nome": sess.get("nome") or "?",
                    "cliente": "",
                    "status": st,
                    "nivel": "ruim",
                    "url": "",
                    "numero": sess.get("numero"),
                }
            )

    return {
        "generatedAt": overview.get("generatedAt"),
        "saudeGeral": overview.get("saudeGeral"),
        "servidores": overview.get("servidores") or {},
        "clientes_resumo": overview.get("clientes") or {},
        "servicos_http": servicos_http,
        "servicosComFalha": falhas,
        "numeros": numeros,
        "alertas_api": list(overview.get("alertas") or []),
        "itens_alerta": itens_alerta,
    }


def _clientes_problema(clientes_payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(clientes_payload, dict):
        lista = list(clientes_payload.get("clientes") or [])
    elif isinstance(clientes_payload, list):
        lista = clientes_payload
    else:
        lista = []
    out: list[dict[str, Any]] = []
    for c in lista:
        if not isinstance(c, dict):
            continue
        health = str(c.get("health") or "").lower()
        if health in HEALTH_RUIM:
            wh = c.get("webhooks") or {}
            out.append(
                {
                    "id": c.get("id"),
                    "nome": c.get("nome"),
                    "health": health,
                    "webhooks_inativos": (wh.get("inativos") if isinstance(wh, dict) else None),
                    "webhooks_total": (wh.get("total") if isinstance(wh, dict) else None),
                    "exec": c.get("exec"),
                }
            )
    out.sort(key=lambda x: (0 if x.get("health") == "offline" else 1, -(x.get("webhooks_inativos") or 0)))
    return out


async def coletar_overview_leve() -> ColetaResult:
    """Só overview — usado pelo poller de alertas (rápido)."""
    s = get_settings()
    if not s.painel_enabled:
        return resultado_stub(FONTE, "PAINEL_ENABLED=false")
    user, password, token = _credenciais()
    if not user and not token:
        return resultado_erro(FONTE, "Faltam PAINEL_API_USER+PASSWORD ou PAINEL_API_TOKEN")
    try:
        overview = await _client().overview()
        if not isinstance(overview, dict):
            return resultado_erro(FONTE, "overview em formato inesperado")
        norm = normalizar_overview(overview)
        return resultado_ok(
            FONTE,
            {
                "modo": "overview",
                "overview": overview,
                "normalizado": norm,
                "servicos": norm["itens_alerta"],  # compat alert_poller
                "totais": {
                    "servicos_http": len(norm["servicos_http"]),
                    "com_problema": len(norm["itens_alerta"]),
                    "saudeGeral": norm["saudeGeral"],
                },
                "com_problema": norm["itens_alerta"],
            },
        )
    except httpx.HTTPStatusError as e:
        logger.exception("painel overview HTTP %s", e.response.status_code)
        return resultado_erro(FONTE, f"HTTP {e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:
        logger.exception("painel overview falhou")
        return resultado_erro(FONTE, str(e))


async def coletar() -> ColetaResult:
    """Coleta completa p/ relatório (usa /api/relatorio-diario quando possível)."""
    s = get_settings()
    if not s.painel_enabled:
        return resultado_stub(
            FONTE,
            "Painel de Serviços ainda não ligado (PAINEL_ENABLED=false).",
        )

    user, password, token = _credenciais()
    if not (s.painel_api_base_url and (user or token)):
        return resultado_erro(
            FONTE,
            "Configure PAINEL_API_BASE_URL e Basic (USER+PASSWORD) ou Bearer TOKEN",
        )

    client = _client()
    try:
        # Endpoint feito sob medida para a IA de relatório.
        relatorio = await client.relatorio_diario()
        if not isinstance(relatorio, dict):
            return resultado_erro(FONTE, "relatorio-diario em formato inesperado")

        overview = relatorio.get("overview") if isinstance(relatorio.get("overview"), dict) else {}
        norm = normalizar_overview(overview) if overview else {
            "itens_alerta": [],
            "alertas_api": list(relatorio.get("alertas") or []),
            "saudeGeral": None,
            "servicos_http": [],
            "servicosComFalha": [],
            "numeros": {},
            "servidores": {},
            "clientes_resumo": {},
        }
        clientes = list(relatorio.get("clientes") or [])
        problemas = _clientes_problema(clientes)

        return resultado_ok(
            FONTE,
            {
                "modo": "relatorio-diario",
                "generatedAt": relatorio.get("generatedAt"),
                "overview": overview,
                "normalizado": norm,
                "custoTotais": relatorio.get("custoTotais"),
                "clientes": clientes,
                "clientes_com_problema": problemas,
                "alertas_api": list(relatorio.get("alertas") or norm.get("alertas_api") or []),
                "servicos": norm.get("itens_alerta") or [],
                "totais": {
                    "clientes": len(clientes),
                    "clientes_problema": len(problemas),
                    "servicos_http": len(norm.get("servicos_http") or []),
                    "com_problema": len(norm.get("itens_alerta") or []),
                    "saudeGeral": norm.get("saudeGeral"),
                },
                "com_problema": norm.get("itens_alerta") or [],
            },
        )
    except httpx.HTTPStatusError as e:
        # Fallback: overview + lista de clientes (sem cold start longo do agregador)
        logger.warning(
            "relatorio-diario HTTP %s — fallback overview+clientes",
            e.response.status_code,
        )
        try:
            overview = await client.overview()
            clientes_raw = await client.listar_clientes()
            if not isinstance(overview, dict):
                return resultado_erro(FONTE, "overview inválido no fallback")
            norm = normalizar_overview(overview)
            problemas = _clientes_problema(clientes_raw if isinstance(clientes_raw, dict) else {})
            return resultado_ok(
                FONTE,
                {
                    "modo": "fallback-overview-clientes",
                    "overview": overview,
                    "normalizado": norm,
                    "clientes": (clientes_raw.get("clientes") if isinstance(clientes_raw, dict) else clientes_raw),
                    "clientes_com_problema": problemas,
                    "alertas_api": norm.get("alertas_api") or [],
                    "servicos": norm.get("itens_alerta") or [],
                    "totais": {
                        "clientes": len(problemas) + (
                            int((overview.get("clientes") or {}).get("operational") or 0)
                        ),
                        "clientes_problema": len(problemas),
                        "servicos_http": len(norm.get("servicos_http") or []),
                        "com_problema": len(norm.get("itens_alerta") or []),
                        "saudeGeral": norm.get("saudeGeral"),
                    },
                    "com_problema": norm.get("itens_alerta") or [],
                    "aviso": f"relatorio-diario falhou HTTP {e.response.status_code}; usei fallback",
                },
            )
        except Exception as e2:
            logger.exception("painel fallback falhou")
            return resultado_erro(FONTE, f"relatorio-diario e fallback falharam: {e2}")
    except Exception as e:
        logger.exception("painel falhou")
        return resultado_erro(FONTE, str(e))
