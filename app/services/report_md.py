"""Montagem determinística do relatório — números iguais ao dash/ops_cache.

O LLM não inventa totais: ou polimos o texto, ou usamos este template.
"""

from __future__ import annotations

from typing import Any


def _n(v: Any, default: int | str = 0) -> Any:
    return default if v is None else v


def _bullets(items: list[str], empty: str = "- (nenhum)") -> list[str]:
    return items if items else [empty]


def montar_relatorio(snapshot: dict[str, Any]) -> str:
    """Relatório escaneável, seções separadas, números do snapshot."""
    alertas = list(snapshot.get("alertas") or [])
    fontes = snapshot.get("fontes") or {}
    gestao = snapshot.get("gestao") if isinstance(snapshot.get("gestao"), dict) else {}
    painel = snapshot.get("painel") if isinstance(snapshot.get("painel"), dict) else {}
    cw = snapshot.get("chatwoot") if isinstance(snapshot.get("chatwoot"), dict) else {}
    waha = snapshot.get("waha") if isinstance(snapshot.get("waha"), dict) else {}
    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}
    tot = gestao.get("totais") if isinstance(gestao.get("totais"), dict) else {}
    kanban = tot.get("kanban") if isinstance(tot.get("kanban"), dict) else {}

    linhas: list[str] = [
        "# Relatório — Infinity Monitor",
        "",
        f"_Gerado em {snapshot.get('gerado_em') or '—'} · rótulo: {snapshot.get('rotulo') or 'manual'}_",
        "",
        "---",
        "",
        "## 1. Resumo executivo",
        "",
    ]
    linhas.extend(_bullets([f"- {a}" for a in alertas[:12]], "- Sem alertas no snapshot."))

    # —— Gestão ——
    linhas += ["", "---", "", "## 2. Gestão Infinity (kanban)", ""]
    if tot:
        linhas += [
            "Contagens **por coluna do painel** (não usar diasAtraso de entregues):",
            "",
            f"| Coluna | Qtd |",
            f"| --- | ---: |",
            f"| Entrada de tarefas | {_n(kanban.get('entrada'), tot.get('entrada', 0))} |",
            f"| Acompanhamento | {_n(kanban.get('acompanhamento'), tot.get('acompanhamento', 0))} |",
            f"| **Atrasado** | **{_n(kanban.get('atrasado'), tot.get('atrasadas', 0))}** |",
            f"| Vencimento hoje | {_n(kanban.get('hoje'), tot.get('vencimento_hoje', 0))} |",
            f"| Vencimento amanhã | {_n(kanban.get('amanha'), tot.get('vencimento_amanha', 0))} |",
            f"| Vencimento essa semana | {_n(kanban.get('semana'), tot.get('vencimento_semana', 0))} |",
            f"| Validação | {_n(kanban.get('validacao'), 0)} |",
            f"| Aguardando cliente | {_n(kanban.get('aguardando'), tot.get('aguardando_cliente', 0))} |",
            f"| Entregues (histórico) | {_n(kanban.get('entregues'), 0)} |",
            "",
            f"Total de tarefas na API: **{_n(tot.get('tarefas'))}**.",
            "",
            "### Top atrasos (coluna Atrasado)",
            "",
        ]
        tops = list(gestao.get("atrasadas_top") or [])[:10]
        if tops:
            for t in tops:
                linhas.append(
                    f"- {t.get('cliente')} · {t.get('projeto')} · {t.get('titulo')} "
                    f"— {t.get('responsavel')} · {t.get('diasAtraso')}d"
                )
        else:
            linhas.append("- Nenhuma tarefa na coluna Atrasado.")

        hoje = list(gestao.get("vencimento_hoje") or [])[:8]
        linhas += ["", "### Vencimento hoje", ""]
        if hoje:
            for t in hoje:
                linhas.append(
                    f"- {t.get('cliente')} · {t.get('titulo')} — {t.get('responsavel')}"
                )
        else:
            linhas.append("- Nenhum.")
    elif gestao.get("erro"):
        linhas.append(f"- Erro Gestão: {gestao.get('erro')}")
    else:
        linhas.append("- Gestão indisponível.")

    # —— Hub ——
    linhas += ["", "---", "", "## 3. Hub de Status", ""]
    saude = (
        (painel.get("totais") or {}).get("saudeGeral")
        if isinstance(painel.get("totais"), dict)
        else None
    ) or painel.get("saudeGeral") or painel.get("aviso") or painel.get("erro") or "—"
    linhas.append(f"**Saúde geral:** {saude}")
    linhas.append("")

    alertas_hub = list(painel.get("alertas_api") or [])
    if not alertas_hub and isinstance(painel.get("alertas"), list):
        for a in painel["alertas"]:
            if isinstance(a, dict):
                alertas_hub.append(a.get("texto") or a.get("log") or str(a))
            else:
                alertas_hub.append(str(a))
    linhas.append("### Alertas do Hub")
    linhas.append("")
    linhas.extend(_bullets([f"- {a}" for a in alertas_hub[:12]]))

    servicos = list(painel.get("servicos_problema") or [])[:15]
    linhas += ["", "### Serviços com problema", ""]
    if servicos:
        for s in servicos:
            if isinstance(s, dict):
                linhas.append(
                    f"- {s.get('nome')} · {s.get('tipo') or '—'} · "
                    f"{s.get('status') or s.get('nivel') or 'problema'}"
                )
            else:
                linhas.append(f"- {s}")
    else:
        linhas.append("- Nenhum serviço crítico listado no cache.")

    clientes_p = list(
        painel.get("clientes_problema") or painel.get("clientes_com_problema") or []
    )[:15]
    linhas += ["", "### Clientes parcial / offline", ""]
    if clientes_p:
        for c in clientes_p:
            if isinstance(c, dict):
                linhas.append(
                    f"- {c.get('nome') or c.get('cliente') or c} · {c.get('status') or c.get('estado') or 'parcial'}"
                )
            else:
                linhas.append(f"- {c}")
    else:
        linhas.append("- Lista detalhada indisponível; ver alertas do Hub acima.")

    if painel.get("atualizado_em") or painel.get("origem"):
        linhas.append("")
        linhas.append(
            f"_Hub origem: {painel.get('origem') or 'coleta'} · "
            f"atualizado {painel.get('atualizado_em') or '—'}_"
        )

    # —— WAHA ——
    linhas += ["", "---", "", "## 4. WAHA (sessões WhatsApp)", ""]
    wt = waha.get("totais") if isinstance(waha.get("totais"), dict) else {}
    working = wt.get("working")
    ruins = wt.get("ruins")
    total = wt.get("total")
    linhas += [
        f"- **WORKING:** {_n(working, '—')}",
        f"- **Ruins / atenção:** {_n(ruins, '—')}",
        f"- **Total sessões:** {_n(total, '—')}",
        "",
    ]
    ruin_list = list(waha.get("ruins") or [])[:20]
    if ruin_list:
        linhas.append("### Sessões fora de WORKING")
        linhas.append("")
        for s in ruin_list:
            if isinstance(s, dict):
                linhas.append(f"- {s.get('name') or s.get('nome')} → **{s.get('status')}**")
            else:
                linhas.append(f"- {s}")
    if waha.get("atualizado_em") or waha.get("origem"):
        linhas.append("")
        linhas.append(
            f"_WAHA origem: {waha.get('origem') or 'coleta'} · "
            f"atualizado {waha.get('atualizado_em') or '—'}_"
        )

    # —— Chatwoot ——
    linhas += ["", "---", "", "## 5. Chatwoot / silêncio da IA", ""]
    ct = cw.get("totais") if isinstance(cw.get("totais"), dict) else {}
    elegiveis = list(cw.get("leads_elegiveis_reprocessamento") or cw.get("elegiveis") or [])
    pausados = list(cw.get("leads_pausados_ignorados") or cw.get("pausados") or [])
    n_el = int(ct.get("elegiveis") if ct.get("elegiveis") is not None else len(elegiveis))
    n_pau = int(
        ct.get("pausados_com_silencio")
        if ct.get("pausados_com_silencio") is not None
        else len(pausados)
    )
    linhas += [
        f"- **Elegíveis a reprocessar:** {n_el}",
        f"- **Pausados (não reprocessar):** {n_pau}",
        f"- Conversas analisadas: {_n(cw.get('conversas_analisadas'), '—')}",
        f"- Silêncio ≥ {_n(cw.get('silencio_minutos'), 5)} min · só hoje: {_n(cw.get('somente_hoje'), True)}",
        "",
        "### Lista elegíveis (top)",
        "",
    ]
    if elegiveis:
        for x in elegiveis[:15]:
            if not isinstance(x, dict):
                continue
            nome = x.get("nome") or x.get("telefone") or "(sem nome)"
            cli = x.get("cliente") or x.get("account_nome") or "—"
            mins = x.get("minutos_sem_resposta")
            link = x.get("link") or ""
            linhas.append(
                f"- **{nome}** · {cli} · conv {x.get('conversation_id')} · "
                f"{mins} min"
                + (f" · [abrir]({link})" if link else "")
            )
    else:
        linhas.append("- Nenhum elegível no snapshot/cache do dash.")

    linhas += ["", "### Reprocessamento automático", ""]
    linhas.append(
        f"- Detecção: ativa · envio auto: "
        f"{'ligado' if repro.get('automatico_habilitado') else 'desligado'}"
    )
    linhas.append(
        f"- Elegíveis detectados: {_n(repro.get('elegiveis_detectados'), n_el)} · "
        f"status lote: {_n(repro.get('status'), '—')} · "
        f"enviados: {_n(repro.get('enviados'), 0)}"
    )
    if repro.get("nota"):
        linhas.append(f"- Nota: {repro.get('nota')}")
    if cw.get("atualizado_em") or cw.get("origem"):
        linhas.append("")
        linhas.append(
            f"_Chatwoot origem: {cw.get('origem') or 'coleta'} · "
            f"atualizado {cw.get('atualizado_em') or '—'}_"
        )

    # —— Ações ——
    linhas += ["", "---", "", "## 6. Ações recomendadas", ""]
    acoes: list[str] = []
    if int(tot.get("atrasadas") or 0) > 0:
        acoes.append(f"- **P0** — Triar as {tot.get('atrasadas')} tarefas da coluna Atrasado.")
    if int(tot.get("vencimento_hoje") or 0) > 0:
        acoes.append(f"- **P0** — Resolver {tot.get('vencimento_hoje')} item(ns) com vencimento hoje.")
    if n_el > 0:
        acoes.append(f"- **P0** — Revisar {n_el} lead(s) Chatwoot elegíveis a reprocessar.")
    if int(ruins or 0) > 0:
        acoes.append(f"- **P1** — Recuperar sessões WAHA ruins ({ruins}); WORKING={working}.")
    if alertas_hub:
        acoes.append("- **P1** — Conferir alertas do Hub listados acima.")
    if not acoes:
        acoes.append("- Sem P0 automático no snapshot.")
    linhas.extend(acoes)

    # —— Fontes ——
    linhas += ["", "---", "", "## 7. Fontes", ""]
    for nome, info in fontes.items():
        if isinstance(info, dict):
            linhas.append(f"- {nome}: **{info.get('status')}**")
        else:
            linhas.append(f"- {nome}: {info}")

    linhas += [
        "",
        "---",
        "",
        "_Relatório montado a partir do snapshot (mesma base do dash). Números não são inventados pelo LLM._",
        "",
    ]
    return "\n".join(str(x) for x in linhas)
