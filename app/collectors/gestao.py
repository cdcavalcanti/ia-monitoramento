"""Collector da API read-only do Gestão Infinity.

Autenticação: header X-Relatorio-Token.
Base: gestao-infinity.ai-infinity.io (configurável).

A lógica de negócio (o que é "atrasado", eficiência, etc.) vive no backend da
plataforma — nós só consumimos. Se o relatório mostrar números estranhos,
checar mudança de regra no front antes de culpar este collector.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok
from app.config import get_settings

logger = logging.getLogger("monitor.gestao")

FONTE = "gestao-infinity"


class GestaoClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-Relatorio-Token": self.token, "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def listar_tarefas(self, **filtros: Any) -> Any:
        params = {k: v for k, v in filtros.items() if v is not None and v != ""}
        return await self._get("/api/tarefas", params)

    async def listar_clientes(self) -> Any:
        return await self._get("/api/clientes")

    async def detalhe_cliente(self, cliente_id: str | int) -> Any:
        return await self._get(f"/api/clientes/{cliente_id}")

    async def projetos_setor(self, cliente_id: str | int, setor_id: str | int) -> Any:
        return await self._get(f"/api/clientes/{cliente_id}/setores/{setor_id}")

    async def detalhe_projeto(self, projeto_id: str | int) -> Any:
        return await self._get(f"/api/projetos/{projeto_id}")

    async def historico_progresso(self, projeto_id: str | int) -> Any:
        return await self._get(f"/api/projetos/{projeto_id}/historico-progresso")

    async def eficiencia(self) -> Any:
        return await self._get("/api/eficiencia")

    async def planejamento(
        self,
        pessoa_id: str,
        semana_inicio: str,
        semana_fim: str,
    ) -> Any:
        return await self._get(
            f"/api/pessoas/{pessoa_id}/planejamento",
            {"semana_inicio": semana_inicio, "semana_fim": semana_fim},
        )


def _segunda_e_domingo(hoje: date | None = None) -> tuple[str, str]:
    """Semana corrente (seg–dom) — datas como YYYY-MM-DD."""
    d = hoje or date.today()
    segunda = d - timedelta(days=d.weekday())
    domingo = segunda + timedelta(days=6)
    return segunda.isoformat(), domingo.isoformat()


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "tarefas", "clientes", "pessoas", "items", "result"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        return [payload]
    return []


def coluna_tarefa(tarefa: dict[str, Any]) -> str:
    """Retorna o id canônico da coluna do kanban (ex.: atrasado, hoje, entregues).

    A API do Gestão devolve `coluna` como objeto `{id, rotulo}` — não como string.
    """
    raw = tarefa.get("coluna") if tarefa.get("coluna") is not None else tarefa.get("status")
    if isinstance(raw, dict):
        return str(raw.get("id") or raw.get("rotulo") or raw.get("nome") or "").strip()
    return str(raw or "").strip()


def coluna_rotulo(tarefa: dict[str, Any]) -> str:
    raw = tarefa.get("coluna") if tarefa.get("coluna") is not None else tarefa.get("status")
    if isinstance(raw, dict):
        return str(raw.get("rotulo") or raw.get("id") or raw.get("nome") or "").strip()
    return str(raw or "").strip()


def tarefa_atrasada(tarefa: dict[str, Any]) -> bool:
    """Só conta o que está na coluna ATRASADO do Gestão — igual ao painel.

    NÃO use diasAtraso sozinho: tarefas Em Entregues ainda carregam diasAtraso
    histórico e inflavam o total (ex.: 552 vs 7 reais).
    """
    col = coluna_tarefa(tarefa).lower()
    return col in {"atrasado", "atrasados", "atrasada"}


async def coletar() -> ColetaResult:
    """Coleta o pacote completo usado pelo relatório diário."""
    s = get_settings()
    if not s.gestao_enabled:
        return resultado_erro(
            FONTE,
            "GESTAO_API_BASE_URL ou RELATORIO_API_TOKEN ausente no ambiente",
        )

    client = GestaoClient(s.gestao_api_base_url, s.relatorio_api_token)
    semana_inicio, semana_fim = _segunda_e_domingo()

    try:
        tarefas_raw = await client.listar_tarefas()
        clientes_raw = await client.listar_clientes()
        eficiencia_raw = await client.eficiencia()
    except httpx.HTTPStatusError as e:
        logger.exception("gestao HTTP %s", e.response.status_code)
        return resultado_erro(FONTE, f"HTTP {e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:
        logger.exception("gestao falhou")
        return resultado_erro(FONTE, str(e))

    tarefas = _as_list(tarefas_raw)
    clientes = _as_list(clientes_raw)
    eficiencia = _as_list(eficiencia_raw)

    # Detalhe dos clientes (carteira, risco, progresso) — N pequeno (~24).
    clientes_detalhe: list[dict[str, Any]] = []
    for c in clientes:
        cid = c.get("id") or c.get("clienteId") or c.get("cliente_id")
        if cid is None:
            clientes_detalhe.append(c)
            continue
        try:
            det = await client.detalhe_cliente(cid)
            if isinstance(det, dict):
                merge = {**c, **det}
            else:
                merge = c
            clientes_detalhe.append(merge)
        except Exception:
            logger.warning("falha ao detalhar cliente %s", cid, exc_info=True)
            clientes_detalhe.append(c)

    # Planejamento semanal por pessoa da tabela de eficiência.
    planejamentos: list[dict[str, Any]] = []
    for pessoa in eficiencia:
        pid = (
            pessoa.get("id")
            or pessoa.get("login")
            or pessoa.get("nome")
            or pessoa.get("responsavel")
        )
        if not pid:
            continue
        try:
            plan = await client.planejamento(str(pid), semana_inicio, semana_fim)
            planejamentos.append(
                {
                    "pessoa": str(pid),
                    "nome": pessoa.get("nome") or str(pid),
                    "semana_inicio": semana_inicio,
                    "semana_fim": semana_fim,
                    "planejamento": plan,
                }
            )
        except Exception:
            logger.warning("planejamento falhou para %s", pid, exc_info=True)
            planejamentos.append(
                {
                    "pessoa": str(pid),
                    "nome": pessoa.get("nome") or str(pid),
                    "semana_inicio": semana_inicio,
                    "semana_fim": semana_fim,
                    "erro": "falha ao buscar planejamento",
                }
            )

    return resultado_ok(
        FONTE,
        {
            "semana_inicio": semana_inicio,
            "semana_fim": semana_fim,
            "tarefas": tarefas,
            "tarefas_total": len(tarefas),
            "clientes": clientes_detalhe,
            "clientes_total": len(clientes_detalhe),
            "eficiencia": eficiencia,
            "planejamentos": planejamentos,
            "meta": {
                "coluna_helper": "campo 'coluna' espelha o kanban do front",
                "resumoStatus": (
                    "texto humano ao concluir tarefa "
                    "(pode estar vazio em tarefas antigas)"
                ),
            },
        },
    )
