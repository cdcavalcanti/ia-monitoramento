"""Montagem determinística do relatório — números iguais ao dash/ops_cache.

O LLM não inventa totais: ou polimos o texto, ou usamos este template.
"""

from __future__ import annotations

from typing import Any


def _n(v: Any, default: int | str = 0) -> Any:
    return default if v is None else v


def _bullets(items: list[str], empty: str = "- (nenhum)") -> list[str]:
    return items if items else [empty]


def criticidade_alerta(texto: str) -> int:
    """Ordem: 0 vermelho → 1 laranja → 2 amarelo → 3 azul."""
    t = str(texto).lower()
    if any(
        k in t
        for k in (
            "atrasad",
            "fora de working",
            " ruin",
            "ruins",
            "failed",
            "erro",
            "offline",
            "crít",
            "critico",
            "crítica",
        )
    ):
        return 0
    if any(
        k in t
        for k in (
            "elegív",
            "elegiv",
            "parcial",
            "aten",
            "problema",
            "s/ resposta",
            "sem resposta",
            "reprocess",
        )
    ):
        return 1
    if any(k in t for k in ("vencimento hoje", "vence hoje", "vencendo hoje", "amanhã", "amanha")):
        return 2
    return 3


def alerta_hub_waha_desatualizado(texto: str) -> bool:
    """Hub às vezes diz 'WAHA não configurada' mesmo com sessões ok no monitor."""
    t = str(texto).lower()
    if "waha" not in t and "números (waha)" not in t and "numeros (waha)" not in t:
        return False
    return any(
        k in t
        for k in (
            "não configur",
            "nao configur",
            "indispon",
            "pendente",
        )
    )


def ordenar_alertas_por_criticidade(alertas: list[Any]) -> list[str]:
    textos = [str(a) for a in alertas if a is not None and str(a).strip()]
    return sorted(textos, key=lambda a: (criticidade_alerta(a), a.lower()))


def filtrar_alertas_hub(
    alertas: list[Any],
    *,
    waha_ok: bool,
) -> list[str]:
    out: list[str] = []
    for a in alertas:
        texto = a.get("texto") or a.get("log") or str(a) if isinstance(a, dict) else str(a)
        # Nunca levar alerta Hub de WAHA "não configurada" para o relatório.
        if alerta_hub_waha_desatualizado(texto):
            continue
        if waha_ok and "waha" in str(texto).lower() and any(
            k in str(texto).lower() for k in ("não configur", "nao configur", "pendente")
        ):
            continue
        out.append(texto)
    return out


def montar_relatorio(snapshot: dict[str, Any]) -> str:
    """Relatório consolidado (escaneável) — números do snapshot."""
    from app.services.report_content import (
        acoes_consolidadas,
        atrasos_por_cliente_rows,
        atrasos_por_resp_rows,
        contas_cw_rows,
        metricas_base,
        panorama_paragrafos,
        scorecard_dominios,
        waha_por_status,
    )

    m = metricas_base(snapshot)
    fontes = snapshot.get("fontes") or {}
    gestao, painel, cw, waha = m["gestao"], m["painel"], m["cw"], m["waha"]
    tot, kanban = m["tot"], m["kanban"]
    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}
    wt = m["wt"]

    waha_ok = m["n_working"] > 0 or m["n_total_w"] > 0
    alertas_raw = list(snapshot.get("alertas") or [])
    alertas = [
        a
        for a in ordenar_alertas_por_criticidade(alertas_raw)
        if not alerta_hub_waha_desatualizado(a)
    ]

    linhas: list[str] = [
        "# Relatório consolidado — Infinity Monitor",
        "",
        f"_Gerado em {snapshot.get('gerado_em') or '—'} · rótulo: {snapshot.get('rotulo') or 'manual'}_",
        "",
        "---",
        "",
        "## 1. Panorama consolidado",
        "",
    ]
    for p in panorama_paragrafos(m):
        linhas.append(p)
        linhas.append("")

    linhas += [
        "### Scorecard por domínio",
        "",
        "| Domínio | Estado | Destaque |",
        "| --- | --- | --- |",
    ]
    for row in scorecard_dominios(m):
        linhas.append(f"| {row['dominio']} | **{row['estado']}** | {row['destaque']} |")

    linhas += ["", "### Sinais por criticidade", ""]
    linhas.extend(_bullets([f"- {a}" for a in alertas[:12]], "- Sem alertas no snapshot."))

    # —— Gestão ——
    from app.services.report_content import tabela_atrasos_detalhe

    linhas += ["", "---", "", "## 2. Gestão Infinity (kanban)", ""]
    if tot:
        linhas += [
            "Contagens **por coluna do painel**:",
            "",
            f"| Coluna | Qtd |",
            f"| --- | ---: |",
            f"| Entrada de tarefas | {_n(kanban.get('entrada'), 0)} |",
            f"| Acompanhamento | {_n(kanban.get('acompanhamento'), 0)} |",
            f"| **Atrasado** | **{m['n_atr']}** |",
            f"| Vencimento hoje | {m['n_hoje']} |",
            f"| Vencimento amanhã | {m['n_amanha']} |",
            f"| Vencimento essa semana | {m['n_semana']} |",
            f"| Validação | {_n(kanban.get('validacao'), 0)} |",
            f"| Aguardando cliente | {m['n_aguard']} |",
            f"| Entregues (histórico) | {_n(kanban.get('entregues'), 0)} |",
            "",
            f"Total de tarefas na API: **{_n(tot.get('tarefas'))}**.",
            "",
            "### Atrasos — detalhe (cliente · projeto · responsável · dias · motivo)",
            "",
        ]
        atr_rows = tabela_atrasos_detalhe(gestao, limite=40)
        if atr_rows:
            # prioriza tabela sem motivo vazio ocupando coluna
            tem_motivo = any(str(r[4]).strip() not in ("", "-", "—", "–") for r in atr_rows)
            if tem_motivo:
                linhas += [
                    "| Cliente | Projeto | Responsável | Dias | Motivo | Tarefa |",
                    "| --- | --- | --- | ---: | --- | --- |",
                ]
                for r in atr_rows:
                    linhas.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
            else:
                linhas += [
                    f"**{m['n_atr']} atrasada(s)**",
                    "",
                    "| Cliente | Projeto | Responsável | Dias | Tarefa |",
                    "| --- | --- | --- | ---: | --- |",
                ]
                for r in atr_rows:
                    linhas.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[5]} |")
            linhas.append("")
            linhas.append("_Motivo ainda não preenchido na Gestão (obrigatório em breve)._")
        else:
            linhas.append("- Nenhuma tarefa na coluna Atrasado.")

        linhas += ["", "### Concentração (resumo)", ""]
        cli_rows = atrasos_por_cliente_rows(gestao, limite=8)
        if cli_rows:
            linhas += ["| Cliente | Qtd | Maior atraso |", "| --- | ---: | --- |"]
            for r in cli_rows:
                linhas.append(f"| {r[0]} | {r[1]} | {r[2]} |")
        resp_rows = atrasos_por_resp_rows(gestao)
        if resp_rows:
            linhas += ["", "| Responsável | Qtd |", "| --- | ---: |"]
            for r in resp_rows:
                linhas.append(f"| {r[0]} | {r[1]} |")

        linhas += ["", "### Acompanhamento — vence hoje / amanhã", ""]
        for titulo, chave in (
            ("Hoje", "vencimento_hoje"),
            ("Amanhã", "vencimento_amanha"),
        ):
            itens = list(gestao.get(chave) or [])
            linhas.append(f"- **{titulo}:** {len(itens)}")
            for t in itens[:5]:
                linhas.append(
                    f"  - {t.get('cliente')} · {t.get('projeto')} · {t.get('titulo')} — {t.get('responsavel')}"
                )
            if len(itens) > 5:
                linhas.append(f"  - +{len(itens) - 5} no kanban")
    elif gestao.get("erro"):
        linhas.append(f"- Erro Gestão: {gestao.get('erro')}")
    else:
        linhas.append("- Gestão indisponível.")

    # —— Hub ——
    linhas += ["", "---", "", "## 3. Hub de Status", ""]
    linhas.append(f"**Saúde geral:** {m['saude']}")
    linhas.append("")

    alertas_hub_raw = list(painel.get("alertas_api") or [])
    if not alertas_hub_raw and isinstance(painel.get("alertas"), list):
        alertas_hub_raw = list(painel["alertas"])
    alertas_hub = filtrar_alertas_hub(alertas_hub_raw, waha_ok=waha_ok)
    linhas.append("### Alertas do Hub")
    linhas.append("")
    if alertas_hub:
        linhas.extend(_bullets([f"- {a}" for a in alertas_hub[:14]]))
    else:
        linhas.append("- Nenhum alerta relevante do Hub.")

    servicos = [s for s in m["servicos"] if isinstance(s, dict)][:15]
    linhas += ["", "### Serviços com problema", ""]
    if servicos:
        for s in servicos:
            linhas.append(
                f"- {s.get('nome')} · {s.get('tipo') or '—'} · "
                f"{s.get('status') or s.get('nivel') or 'problema'}"
            )
    else:
        linhas.append("- Nenhum serviço crítico listado.")

    linhas += ["", "### Clientes parcial / offline", ""]
    if m["clientes_hub"]:
        for c in m["clientes_hub"][:18]:
            if isinstance(c, dict):
                linhas.append(
                    f"- {c.get('nome') or c.get('cliente') or c} · "
                    f"{c.get('status') or c.get('estado') or 'parcial'}"
                )
            else:
                linhas.append(f"- {c}")
    else:
        linhas.append("- Lista detalhada indisponível; ver alertas do Hub acima.")

    # —— WAHA ——
    linhas += ["", "---", "", "## 4. WAHA (sessões WhatsApp)", ""]
    pct = round(100.0 * m["n_working"] / m["n_total_w"]) if m["n_total_w"] else 0
    linhas += [
        f"- **WORKING:** {m['n_working']}",
        f"- **Ruins / atenção:** {m['n_ruins']}",
        f"- **Total sessões:** {m['n_total_w']}",
        f"- **% OK:** {pct}%",
        "",
    ]
    by_st = waha_por_status(waha)
    if by_st:
        linhas += ["### Distribuição dos ruins", ""]
        for st, n in by_st:
            linhas.append(f"- `{st}`: {n}")
        linhas.append("")
    ruin_list = list(waha.get("ruins") or [])[:18]
    if ruin_list:
        linhas.append(f"### Sessões fora de WORKING (amostra {len(ruin_list)})")
        linhas.append("")
        for s in ruin_list:
            if isinstance(s, dict):
                linhas.append(
                    f"- **{s.get('name') or s.get('nome')}** · status `{s.get('status')}`"
                )
            else:
                linhas.append(f"- {s}")

    # —— Chatwoot (SÓ HOJE) ——
    linhas += ["", "---", "", "## 5. Chatwoot — reprocessamento do dia", ""]
    limiar = _n(cw.get("silencio_minutos"), 5)
    if cw.get("aviso_dia"):
        linhas.append(f"- **Aviso:** {cw.get('aviso_dia')}")
    linhas += [
        f"- **Elegíveis HOJE:** {m['n_el']}",
        f"- **Reprocessados HOJE (enviados):** {m.get('n_repro_dia', 0)}",
        f"- Pausados / handoff (não reprocessar): {m['n_pau']}",
        f"- Critério: incoming de **hoje** (America/Sao_Paulo) · s/ resposta ≥ {limiar} min · "
        f"sem pausa/skip/handoff",
        "",
    ]

    linhas += ["### Contas com elegíveis hoje", ""]
    crows = [r for r in contas_cw_rows(cw, so_com_sinal=True) if r[1] != "0"]
    if crows:
        linhas += ["| Conta | Elegíveis hoje |", "| --- | ---: |"]
        for r in crows[:12]:
            linhas.append(f"| {r[0]} | {r[1]} |")
    else:
        linhas.append("- Nenhuma conta com elegível hoje.")

    linhas += ["", "### Leads elegíveis hoje", ""]
    if m["elegiveis"]:
        linhas += [
            "| Lead | Conta | Id conversa | S/ resposta | Incoming |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for x in m["elegiveis"][:20]:
            if not isinstance(x, dict):
                continue
            nome = x.get("nome") or x.get("telefone") or "(sem nome)"
            cli = x.get("cliente") or x.get("account_nome") or "—"
            mins = x.get("minutos_sem_resposta")
            cid = x.get("conversation_id")
            when = str(x.get("ultimo_incoming_em") or "")[:19]
            linhas.append(f"| {nome} | {cli} | `{cid}` | {mins} min | {when} |")
    else:
        linhas.append("- Nenhum elegível **hoje** (leads de dias anteriores são ignorados).")

    linhas += ["", "### Lote de reprocessamento (hoje)", ""]
    linhas.append(
        f"- Envio automático: "
        f"{'ligado' if repro.get('automatico_habilitado') else 'desligado'}"
    )
    linhas.append(
        f"- Elegíveis detectados hoje: **{m['n_el']}** · "
        f"enviados hoje: **{m.get('n_repro_dia', 0)}** · "
        f"status: {_n(repro.get('status'), '—')}"
    )
    if repro.get("nota"):
        linhas.append(f"- Nota: {repro.get('nota')}")


    # —— Ações ——
    linhas += ["", "---", "", "## 6. Plano de ação consolidado", ""]
    linhas.append(
        "_Prioridades derivadas do cruzamento Gestão + Hub + WAHA + Chatwoot._"
    )
    linhas.append("")
    for text, _tone in acoes_consolidadas(m):
        linhas.append(f"- {text}")

    # —— Fontes ——
    linhas += ["", "---", "", "## 7. Fontes e frescor", ""]
    for nome, info in fontes.items():
        if isinstance(info, dict):
            linhas.append(f"- {nome}: **{info.get('status')}**")
        else:
            linhas.append(f"- {nome}: {info}")
    for nome, bloco in (("Hub", painel), ("WAHA", waha), ("Chatwoot", cw)):
        if isinstance(bloco, dict) and (bloco.get("atualizado_em") or bloco.get("origem")):
            linhas.append(
                f"- {nome} atualizado: {bloco.get('atualizado_em') or '—'} · "
                f"origem {bloco.get('origem') or 'coleta'}"
            )

    linhas += [
        "",
        "---",
        "",
        "_Relatório consolidado a partir do snapshot (mesma base do dash). Números não são inventados pelo LLM._",
        "",
    ]
    return "\n".join(str(x) for x in linhas)
