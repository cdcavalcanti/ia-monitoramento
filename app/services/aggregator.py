"""Agregação determinística — o LLM não decide o que está atrasado.

Espelha o padrão do realdeal-sdr: classificação fora do modelo
(services/roteamento.py). Aqui condensamos 580+ tarefas num snapshot
objetivo para o relatório.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from app.collectors.base import ColetaResult
from app.collectors.gestao import coluna_tarefa, tarefa_atrasada


# Colunas que indicam trabalho em andamento (heurística; o front é a fonte).
COLUNAS_EM_DESENVOLVIMENTO = {
    "desenvolvimento",
    "desenvolv.",
    "em desenvolvimento",
    "produção",
    "producao",
    "andamento",
    "mapeamento",
    "validação",
    "validacao",
}


def _nome_cliente(t: dict[str, Any]) -> str:
    return str(
        t.get("cliente")
        or t.get("clienteNome")
        or t.get("nomeCliente")
        or t.get("cliente_nome")
        or "?"
    )


def _nome_projeto(t: dict[str, Any]) -> str:
    return str(
        t.get("projeto")
        or t.get("projetoNome")
        or t.get("nomeProjeto")
        or t.get("projeto_nome")
        or "?"
    )


def _responsavel(t: dict[str, Any]) -> str:
    return str(
        t.get("responsavel")
        or t.get("responsavelNome")
        or t.get("assignee")
        or "?"
    )


def _titulo(t: dict[str, Any]) -> str:
    return str(t.get("titulo") or t.get("title") or t.get("nome") or t.get("tarefa") or "?")


def _resumo_tarefa(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": _titulo(t),
        "cliente": _nome_cliente(t),
        "projeto": _nome_projeto(t),
        "responsavel": _responsavel(t),
        "coluna": coluna_tarefa(t),
        "diasAtraso": t.get("diasAtraso") or t.get("dias_atraso") or 0,
        "resumoStatus": t.get("resumoStatus") or t.get("resumo_status") or "",
        "prazo": t.get("prazo") or t.get("dataPrazo") or t.get("due_date") or "",
    }


def _agregar_gestao(dados: dict[str, Any]) -> dict[str, Any]:
    tarefas: list[dict[str, Any]] = list(dados.get("tarefas") or [])
    clientes: list[dict[str, Any]] = list(dados.get("clientes") or [])
    eficiencia: list[dict[str, Any]] = list(dados.get("eficiencia") or [])
    planejamentos: list[dict[str, Any]] = list(dados.get("planejamentos") or [])

    por_coluna: Counter[str] = Counter()
    atrasadas: list[dict[str, Any]] = []
    em_dev: list[dict[str, Any]] = []
    vencendo_hoje: list[dict[str, Any]] = []
    aguardando_cliente: list[dict[str, Any]] = []
    concluidas_com_resumo: list[dict[str, Any]] = []

    atrasos_por_cliente: dict[str, list[dict[str, Any]]] = defaultdict(list)
    atrasos_por_resp: Counter[str] = Counter()

    for t in tarefas:
        col = coluna_tarefa(t)
        col_l = col.lower()
        por_coluna[col or "(sem coluna)"] += 1

        if tarefa_atrasada(t):
            item = _resumo_tarefa(t)
            atrasadas.append(item)
            atrasos_por_cliente[_nome_cliente(t)].append(item)
            atrasos_por_resp[_responsavel(t)] += 1

        if any(k in col_l for k in COLUNAS_EM_DESENVOLVIMENTO) or "desenvolv" in col_l:
            em_dev.append(_resumo_tarefa(t))

        if "vencimento hoje" in col_l or col_l == "hoje":
            vencendo_hoje.append(_resumo_tarefa(t))

        if "aguardando cliente" in col_l:
            aguardando_cliente.append(_resumo_tarefa(t))

        resumo = t.get("resumoStatus") or t.get("resumo_status")
        if resumo:
            concluidas_com_resumo.append(
                {
                    **_resumo_tarefa(t),
                    "resumoStatus": str(resumo)[:500],
                }
            )

    # Ordena atrasos: mais dias primeiro.
    def _dias(x: dict[str, Any]) -> int:
        try:
            return int(x.get("diasAtraso") or 0)
        except (TypeError, ValueError):
            return 0

    atrasadas.sort(key=_dias, reverse=True)

    clientes_risco: list[dict[str, Any]] = []
    for c in clientes:
        risco = c.get("projetosEmRisco") or c.get("projetos_em_risco") or c.get("emRisco") or 0
        try:
            risco_n = int(risco)
        except (TypeError, ValueError):
            risco_n = 0
        pct = c.get("pctNoPrazo") or c.get("percentualNoPrazo") or c.get("pct_no_prazo")
        progresso = c.get("progressoMedio") or c.get("progresso_medio") or c.get("progresso")
        clientes_risco.append(
            {
                "id": c.get("id"),
                "nome": c.get("nome") or c.get("name") or "?",
                "carteira": c.get("carteira") or c.get("valorCarteira"),
                "pctNoPrazo": pct,
                "progressoMedio": progresso,
                "projetosEmRisco": risco_n,
                "setores": c.get("setores") or c.get("setoresCount") or c.get("qtdSetores"),
            }
        )
    clientes_risco.sort(key=lambda x: int(x.get("projetosEmRisco") or 0), reverse=True)

    # Planejamento: resume contagem por pessoa (sem jogar o JSON cru no prompt).
    planejamento_resumo: list[dict[str, Any]] = []
    for p in planejamentos:
        plan = p.get("planejamento")
        qtd = 0
        if isinstance(plan, list):
            qtd = len(plan)
        elif isinstance(plan, dict):
            # pode vir { "segunda": [...], ... } ou { "dias": [...] }
            if "dias" in plan and isinstance(plan["dias"], list):
                qtd = sum(len(d.get("tarefas") or []) if isinstance(d, dict) else 0 for d in plan["dias"])
            else:
                for v in plan.values():
                    if isinstance(v, list):
                        qtd += len(v)
                    elif isinstance(v, dict) and isinstance(v.get("tarefas"), list):
                        qtd += len(v["tarefas"])
        planejamento_resumo.append(
            {
                "pessoa": p.get("nome") or p.get("pessoa"),
                "tarefas_planejadas_semana": qtd,
                "erro": p.get("erro"),
                "amostra": _amostra_planejamento(plan, limite=8),
            }
        )

    return {
        "semana_inicio": dados.get("semana_inicio"),
        "semana_fim": dados.get("semana_fim"),
        "totais": {
            "tarefas": len(tarefas),
            "atrasadas": len(atrasadas),
            "em_desenvolvimento": len(em_dev),
            "vencimento_hoje": len(vencendo_hoje),
            "aguardando_cliente": len(aguardando_cliente),
            "clientes": len(clientes),
            "com_resumo_status": len(concluidas_com_resumo),
        },
        "por_coluna": dict(por_coluna.most_common()),
        "atrasadas_top": atrasadas[:40],
        "atrasos_por_cliente": {
            k: v[:15] for k, v in sorted(atrasos_por_cliente.items(), key=lambda kv: -len(kv[1]))[:20]
        },
        "atrasos_por_responsavel": dict(atrasos_por_resp.most_common(20)),
        "em_desenvolvimento_amostra": em_dev[:30],
        "vencimento_hoje": vencendo_hoje[:20],
        "aguardando_cliente": aguardando_cliente[:20],
        "resumos_recentes": concluidas_com_resumo[-25:],
        "clientes": clientes_risco,
        "eficiencia": eficiencia,
        "planejamento_semana": planejamento_resumo,
    }


def _amostra_planejamento(plan: Any, limite: int = 8) -> list[str]:
    titulos: list[str] = []

    def _push(item: Any) -> None:
        if len(titulos) >= limite:
            return
        if isinstance(item, dict):
            titulos.append(str(item.get("titulo") or item.get("nome") or item.get("tarefa") or item))
        elif isinstance(item, str):
            titulos.append(item)

    if isinstance(plan, list):
        for item in plan:
            _push(item)
            if len(titulos) >= limite:
                break
    elif isinstance(plan, dict):
        for v in plan.values():
            if isinstance(v, list):
                for item in v:
                    _push(item)
                    if len(titulos) >= limite:
                        return titulos
            elif isinstance(v, dict):
                for item in v.get("tarefas") or []:
                    _push(item)
                    if len(titulos) >= limite:
                        return titulos
    return titulos


def agregar(coletas: dict[str, ColetaResult]) -> dict[str, Any]:
    """Monta o snapshot consolidado a partir das coletas brutas."""
    gestao = coletas.get("gestao")
    painel = coletas.get("painel")
    chatwoot = coletas.get("chatwoot")
    waha = coletas.get("waha")

    snapshot: dict[str, Any] = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fontes": {
            "gestao": {"status": gestao["status"] if gestao else "ausente", "fonte": gestao["fonte"] if gestao else None},
            "painel": {"status": painel["status"] if painel else "ausente", "fonte": painel["fonte"] if painel else None},
            "chatwoot": {
                "status": chatwoot["status"] if chatwoot else "ausente",
                "fonte": chatwoot["fonte"] if chatwoot else None,
            },
            "waha": {"status": waha["status"] if waha else "ausente", "fonte": waha["fonte"] if waha else None},
        },
        "gestao": None,
        "painel": None,
        "chatwoot": None,
        "waha": None,
        "alertas": [],
    }

    if gestao and gestao["status"] == "ok":
        snapshot["gestao"] = _agregar_gestao(gestao["dados"])
        tot = snapshot["gestao"]["totais"]
        if tot["atrasadas"] > 0:
            snapshot["alertas"].append(f"{tot['atrasadas']} tarefa(s) atrasada(s) no Gestão.")
        if tot["vencimento_hoje"] > 0:
            snapshot["alertas"].append(f"{tot['vencimento_hoje']} tarefa(s) com vencimento hoje.")
    elif gestao:
        snapshot["gestao"] = gestao["dados"]
        snapshot["alertas"].append(f"Gestão: status={gestao['status']} — ver dados/erro.")

    if painel:
        snapshot["painel"] = painel["dados"]
        if painel["status"] == "stub":
            snapshot["alertas"].append("Painel de Serviços ainda não integrado (stub).")
        elif painel["status"] == "erro":
            snapshot["alertas"].append(f"Painel com erro: {painel['dados'].get('erro')}")

    if chatwoot:
        snapshot["chatwoot"] = chatwoot["dados"]
        if chatwoot["status"] == "stub":
            snapshot["alertas"].append("Chatwoot/IAs ainda não integrado (stub).")
        elif chatwoot["status"] == "erro":
            snapshot["alertas"].append(f"Chatwoot com erro: {chatwoot['dados'].get('erro')}")
        elif chatwoot["status"] == "ok":
            totais = (chatwoot["dados"] or {}).get("totais") or {}
            n_el = int(totais.get("elegiveis") or 0)
            n_pau = int(totais.get("pausados_com_silencio") or 0)
            if n_el > 0:
                snapshot["alertas"].append(
                    f"{n_el} lead(s) sem resposta da IA (>threshold) elegíveis a reprocessar."
                )
            if n_pau > 0:
                snapshot["alertas"].append(
                    f"{n_pau} lead(s) em silêncio mas com etiqueta de pausa — não reprocessar."
                )

    if waha:
        snapshot["waha"] = waha["dados"]
        if waha["status"] == "stub":
            snapshot["alertas"].append("Monitoramento de sessões WAHA desligado (stub).")
        elif waha["status"] == "erro":
            snapshot["alertas"].append(f"WAHA com erro: {waha['dados'].get('erro')}")
        elif waha["status"] == "ok":
            tot = (waha["dados"] or {}).get("totais") or {}
            n_ruim = int(tot.get("ruins") or 0)
            if n_ruim > 0:
                snapshot["alertas"].append(f"{n_ruim} sessão(ões) WAHA fora de WORKING.")

    return snapshot
