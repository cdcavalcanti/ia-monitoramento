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
from app.collectors.gestao import coluna_rotulo, coluna_tarefa, tarefa_atrasada


# Colunas do kanban Gestão (id da API) — espelha o painel.
COLUNA_ATRASADO = {"atrasado", "atrasados", "atrasada"}
COLUNA_HOJE = {"hoje"}
COLUNA_AMANHA = {"amanha", "amanhã"}
COLUNA_SEMANA = {"semana"}
COLUNA_AGUARDANDO = {"aguardando"}
COLUNA_VALIDACAO = {"validacao", "validação"}
COLUNA_ACOMPANHAMENTO = {"acompanhamento"}
COLUNA_ENTRADA = {"entrada", "programadas"}
COLUNA_ENTREGUES = {"entregues", "descontinuadas"}



def _nome_de_campo(val: Any, *keys: str) -> str:
    if isinstance(val, dict):
        for k in keys or ("nome", "name", "titulo", "label", "id"):
            if val.get(k) not in (None, ""):
                return str(val.get(k))
        return str(val)
    if val is None:
        return "?"
    return str(val)


def _nome_cliente(t: dict[str, Any]) -> str:
    for key in ("cliente", "clienteNome", "nomeCliente", "cliente_nome"):
        if t.get(key) is not None:
            return _nome_de_campo(t.get(key), "nome", "name", "titulo", "id")
    return "?"


def _nome_projeto(t: dict[str, Any]) -> str:
    for key in ("projeto", "projetoNome", "nomeProjeto", "projeto_nome"):
        if t.get(key) is not None:
            return _nome_de_campo(t.get(key), "nome", "name", "titulo", "id")
    return "?"


def _responsavel(t: dict[str, Any]) -> str:
    for key in ("responsavel", "responsavelNome", "assignee"):
        if t.get(key) is not None:
            return _nome_de_campo(t.get(key), "nome", "name", "titulo", "id")
    return "?"


def _titulo(t: dict[str, Any]) -> str:
    return str(t.get("titulo") or t.get("title") or t.get("nome") or t.get("tarefa") or "?")


def _motivo_atraso(t: dict[str, Any]) -> str:
    """Campo obrigatório de motivo (em breve na Gestão). Aceita aliases atuais."""
    for key in (
        "motivoAtraso",
        "motivo_atraso",
        "porqueAtraso",
        "porque_atraso",
        "justificativaAtraso",
        "justificativa_atraso",
        "motivo",
        "porque",
        "observacaoAtraso",
        "observacao_atraso",
    ):
        val = t.get(key)
        if val is None or val == "":
            continue
        if isinstance(val, dict):
            txt = val.get("texto") or val.get("nome") or val.get("titulo") or ""
            if str(txt).strip():
                return str(txt).strip()
        else:
            if str(val).strip():
                return str(val).strip()
    return ""


def _resumo_tarefa(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": _titulo(t),
        "cliente": _nome_cliente(t),
        "projeto": _nome_projeto(t),
        "responsavel": _responsavel(t),
        "coluna": coluna_tarefa(t),
        "coluna_rotulo": coluna_rotulo(t),
        "diasAtraso": t.get("diasAtraso") or t.get("dias_atraso") or 0,
        "resumoStatus": t.get("resumoStatus") or t.get("resumo_status") or "",
        "motivo": _motivo_atraso(t),
        "prazo": t.get("prazo") or t.get("dataPrazo") or t.get("due_date") or "",
    }


def _agregar_gestao(dados: dict[str, Any]) -> dict[str, Any]:
    tarefas: list[dict[str, Any]] = list(dados.get("tarefas") or [])
    clientes: list[dict[str, Any]] = list(dados.get("clientes") or [])
    eficiencia: list[dict[str, Any]] = list(dados.get("eficiencia") or [])
    planejamentos: list[dict[str, Any]] = list(dados.get("planejamentos") or [])

    por_coluna: Counter[str] = Counter()
    por_coluna_id: Counter[str] = Counter()
    atrasadas: list[dict[str, Any]] = []
    em_dev: list[dict[str, Any]] = []
    vencendo_hoje: list[dict[str, Any]] = []
    vencendo_amanha: list[dict[str, Any]] = []
    vencendo_semana: list[dict[str, Any]] = []
    aguardando_cliente: list[dict[str, Any]] = []
    entrada: list[dict[str, Any]] = []
    acompanhamento: list[dict[str, Any]] = []
    concluidas_com_resumo: list[dict[str, Any]] = []

    atrasos_por_cliente: dict[str, list[dict[str, Any]]] = defaultdict(list)
    atrasos_por_resp: Counter[str] = Counter()

    for t in tarefas:
        col_id = coluna_tarefa(t).lower()
        col_label = coluna_rotulo(t) or col_id or "(sem coluna)"
        por_coluna[col_label] += 1
        por_coluna_id[col_id or "(sem)"] += 1
        item = _resumo_tarefa(t)

        if tarefa_atrasada(t) or col_id in COLUNA_ATRASADO:
            atrasadas.append(item)
            atrasos_por_cliente[_nome_cliente(t)].append(item)
            atrasos_por_resp[_responsavel(t)] += 1

        if col_id in COLUNA_HOJE:
            vencendo_hoje.append(item)
        if col_id in COLUNA_AMANHA:
            vencendo_amanha.append(item)
        if col_id in COLUNA_SEMANA:
            vencendo_semana.append(item)
        if col_id in COLUNA_AGUARDANDO:
            aguardando_cliente.append(item)
        if col_id in COLUNA_ENTRADA:
            entrada.append(item)
        if col_id in COLUNA_ACOMPANHAMENTO:
            acompanhamento.append(item)
        if col_id in COLUNA_VALIDACAO or "desenvolv" in col_id:
            em_dev.append(item)

        resumo = t.get("resumoStatus") or t.get("resumo_status")
        if resumo and col_id in COLUNA_ENTREGUES:
            concluidas_com_resumo.append({**item, "resumoStatus": str(resumo)[:500]})

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
            "entrada": len(entrada),
            "acompanhamento": len(acompanhamento),
            "em_desenvolvimento": len(em_dev),
            "vencimento_hoje": len(vencendo_hoje),
            "vencimento_amanha": len(vencendo_amanha),
            "vencimento_semana": len(vencendo_semana),
            "aguardando_cliente": len(aguardando_cliente),
            "clientes": len(clientes),
            "com_resumo_status": len(concluidas_com_resumo),
            "kanban": {
                "entrada": int(por_coluna_id.get("entrada") or 0),
                "acompanhamento": int(por_coluna_id.get("acompanhamento") or 0),
                "atrasado": int(por_coluna_id.get("atrasado") or 0),
                "hoje": int(por_coluna_id.get("hoje") or 0),
                "amanha": int(por_coluna_id.get("amanha") or 0),
                "semana": int(por_coluna_id.get("semana") or 0),
                "validacao": int(por_coluna_id.get("validacao") or 0),
                "aguardando": int(por_coluna_id.get("aguardando") or 0),
                "entregues": int(por_coluna_id.get("entregues") or 0),
            },
        },
        "por_coluna": dict(por_coluna.most_common()),
        "por_coluna_id": dict(por_coluna_id.most_common()),
        "atrasadas_top": atrasadas[:40],
        "atrasos_por_cliente": {
            k: v[:15] for k, v in sorted(atrasos_por_cliente.items(), key=lambda kv: -len(kv[1]))[:20]
        },
        "atrasos_por_responsavel": dict(atrasos_por_resp.most_common(20)),
        "em_desenvolvimento_amostra": em_dev[:30],
        "vencimento_hoje": vencendo_hoje[:20],
        "vencimento_amanha": vencendo_amanha[:20],
        "vencimento_semana": vencendo_semana[:20],
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


def _sanear_chatwoot_no_snapshot(dados: dict[str, Any]) -> dict[str, Any]:
    """Garante elegíveis só do dia corrente — cache antigo não entra no relatório."""
    from app.services.report_content import sanear_chatwoot_somente_hoje

    return sanear_chatwoot_somente_hoje(dados)


def agregar(coletas: dict[str, ColetaResult]) -> dict[str, Any]:
    """Monta o snapshot consolidado a partir das coletas brutas."""
    gestao = coletas.get("gestao")
    painel = coletas.get("painel")
    chatwoot = coletas.get("chatwoot")
    waha = coletas.get("waha")

    snapshot: dict[str, Any] = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "escopo": (
            "Relatório consolidado do ecossistema Infinity: "
            "Gestão (tarefas/atrasos), Hub de Status (serviços/clientes), "
            "WAHA (sessões WhatsApp), Chatwoot (s/ resposta IA / reprocess)."
        ),
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
        "reprocessamento": None,
        "alertas": [],
    }

    if gestao and gestao["status"] == "ok":
        snapshot["gestao"] = _agregar_gestao(gestao["dados"])
        tot = snapshot["gestao"]["totais"]
        if tot["atrasadas"] > 0:
            snapshot["alertas"].append(
                f"{tot['atrasadas']} tarefa(s) na coluna Atrasado do Gestão (kanban)."
            )
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
        elif painel["status"] == "ok":
            dados = painel["dados"] or {}
            tot = dados.get("totais") or {}
            saude = (
                tot.get("saudeGeral")
                or dados.get("saudeGeral")
                or (dados.get("normalizado") or {}).get("saudeGeral")
            )
            if saude:
                snapshot["alertas"].append(f"Hub de Status — saúde geral: {saude}.")
            n_prob = int(tot.get("com_problema") or 0) or len(dados.get("servicos_problema") or [])
            if n_prob > 0:
                snapshot["alertas"].append(f"{n_prob} item(ns) com problema no Hub (serviço/WAHA).")
            clientes_p = dados.get("clientes_problema") or []
            n_cli = int(tot.get("clientes_problema") or 0) or len(clientes_p)
            if n_cli > 0:
                snapshot["alertas"].append(f"{n_cli} cliente(s) partial/offline no Hub.")
            alertas_hub = list(dados.get("alertas_api") or [])
            if not alertas_hub:
                for a in dados.get("alertas") or []:
                    if isinstance(a, dict):
                        alertas_hub.append(a.get("texto") or a.get("log") or str(a))
                    else:
                        alertas_hub.append(str(a))
            # Sessões WAHA reais vêm do collector WAHA — ignora alerta Hub desatualizado.
            waha_vivo = bool(
                waha
                and waha.get("status") == "ok"
                and isinstance(waha.get("dados"), dict)
                and (waha["dados"].get("totais") or {})
            )
            for a in alertas_hub[:8]:
                texto = str(a)
                t = texto.lower()
                if waha_vivo and "waha" in t and any(
                    k in t for k in ("não configur", "nao configur", "indispon", "pendente")
                ):
                    continue
                snapshot["alertas"].append(f"Hub: {texto}")

    if chatwoot:
        dados_cw = chatwoot["dados"] if isinstance(chatwoot.get("dados"), dict) else {}
        if chatwoot["status"] == "ok" and dados_cw:
            dados_cw = _sanear_chatwoot_no_snapshot(dados_cw)
        snapshot["chatwoot"] = dados_cw if chatwoot["status"] == "ok" else chatwoot["dados"]
        if chatwoot["status"] == "stub":
            snapshot["alertas"].append("Chatwoot/IAs ainda não integrado (stub).")
        elif chatwoot["status"] == "erro":
            snapshot["alertas"].append(f"Chatwoot com erro: {chatwoot['dados'].get('erro')}")
        elif chatwoot["status"] == "ok":
            totais = (snapshot["chatwoot"] or {}).get("totais") or {}
            n_el = int(totais.get("elegiveis") or 0)
            n_pau = int(totais.get("pausados_com_silencio") or 0)
            n_contas = int(totais.get("contas") or 0)
            if n_el > 0:
                prefix = f"{n_contas} conta(s) cliente — " if n_contas else ""
                snapshot["alertas"].append(
                    f"{prefix}{n_el} lead(s) s/ resposta da IA HOJE (elegíveis a reprocessar)."
                )
            if n_pau > 0:
                snapshot["alertas"].append(
                    f"{n_pau} lead(s) s/ resposta com etiqueta de pausa — não reprocessar."
                )

    if waha:
        snapshot["waha"] = waha["dados"]
        if waha["status"] == "stub":
            snapshot["alertas"].append("Monitoramento de sessões WAHA desligado (stub).")
        elif waha["status"] == "erro":
            snapshot["alertas"].append(f"WAHA com erro: {waha['dados'].get('erro')}")
        elif waha["status"] == "ok":
            tot = (waha["dados"] or {}).get("totais") or {}
            n_ok = int(tot.get("working") or 0)
            n_ruim = int(tot.get("ruins") or 0)
            n_tot = int(tot.get("total") or 0)
            snapshot["alertas"].append(
                f"WAHA: {n_ok} WORKING / {n_ruim} ruins / {n_tot} total."
            )
            if n_ruim > 0:
                snapshot["alertas"].append(f"{n_ruim} sessão(ões) WAHA fora de WORKING.")

    from app.services.report_md import ordenar_alertas_por_criticidade

    snapshot["alertas"] = ordenar_alertas_por_criticidade(snapshot["alertas"])
    return snapshot
