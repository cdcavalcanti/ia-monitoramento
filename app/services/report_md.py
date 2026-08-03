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
    """Filtra qualquer menção WAHA do Hub (WAHA saiu do monitor)."""
    t = str(texto).lower()
    return "waha" in t or "números (waha)" in t or "numeros (waha)" in t


def ordenar_alertas_por_criticidade(alertas: list[Any]) -> list[str]:
    textos = [str(a) for a in alertas if a is not None and str(a).strip()]
    return sorted(textos, key=lambda a: (criticidade_alerta(a), a.lower()))


def filtrar_alertas_hub(
    alertas: list[Any],
    *,
    waha_ok: bool = True,
) -> list[str]:
    out: list[str] = []
    for a in alertas:
        texto = a.get("texto") or a.get("log") or str(a) if isinstance(a, dict) else str(a)
        if alerta_hub_waha_desatualizado(texto):
            continue
        out.append(texto)
    return out


def montar_relatorio(snapshot: dict[str, Any]) -> str:
    """Relatório consolidado (escaneável) — números do snapshot."""
    from app.services.report_content import (
        acoes_consolidadas,
        contas_cw_rows,
        gestao_por_cliente,
        metricas_base,
        panorama_paragrafos,
        scorecard_dominios,
        tarefas_rows,
    )

    m = metricas_base(snapshot)
    fontes = snapshot.get("fontes") or {}
    gestao, painel, cw = m["gestao"], m["painel"], m["cw"]
    tot = m["tot"]
    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}

    from app.services.tempo import carimbo_relatorio, hoje_br

    carimbo = carimbo_relatorio()
    dia_br = hoje_br()

    alertas_raw = list(snapshot.get("alertas") or [])
    alertas = [
        a
        for a in ordenar_alertas_por_criticidade(alertas_raw)
        if not alerta_hub_waha_desatualizado(a)
    ]

    linhas: list[str] = [
        "# Relatório consolidado — Infinity Monitor",
        "",
        f"**HOJE: {dia_br}** (America/Sao_Paulo) · gerado {carimbo['gerado_em_br']} · "
        f"rótulo: {snapshot.get('rotulo') or 'manual'}",
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

    # —— Gestão por cliente ——
    linhas += ["", "---", "", "## 2. Gestão por cliente", ""]
    if tot:
        linhas += [
            f"Totais do kanban: **{m['n_atr']}** atrasada(s) · **{m['n_hoje']}** hoje · "
            f"**{m['n_amanha']}** amanhã · **{m['n_semana']}** na semana · "
            f"**{m['n_aguard']}** aguardando · "
            f"**{m.get('n_clientes_ativos') or 0}** cliente(s) com fila ativa "
            f"(API: {_n(tot.get('tarefas'))} tarefas).",
            "",
        ]
        blocos = gestao_por_cliente(gestao, limite=25)
        if not blocos:
            linhas.append("- Nenhum cliente com atraso / hoje / semana no snapshot.")
        for bloco in blocos:
            met = bloco.get("metricas") or {}
            nome = bloco.get("cliente") or "?"
            projetos = list(bloco.get("projetos") or [])
            linhas += [
                f"### {nome}",
                "",
                f"- **Projetos:** {', '.join(projetos) if projetos else '—'}",
                f"- **Filas:** {met.get('atrasadas', 0)} atrasada(s) · "
                f"{met.get('hoje', 0)} hoje · {met.get('amanha', 0)} amanhã · "
                f"{met.get('semana', 0)} na semana · {met.get('aguardando', 0)} aguardando",
                "",
            ]

            atr = list(bloco.get("atrasadas") or [])
            if atr:
                linhas += [
                    "#### Atrasadas — resolver",
                    "",
                    "| Projeto | Responsável | Dias | Tarefa |",
                    "| --- | --- | ---: | --- |",
                ]
                for r in tarefas_rows(atr, com_dias=True, limite=15):
                    linhas.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
                linhas.append("")

            plan = list(bloco.get("planejamento_semana") or [])
            if plan:
                linhas += [
                    "#### Planejamento da semana (hoje · amanhã · semana)",
                    "",
                    "| Projeto | Responsável | Tarefa |",
                    "| --- | --- | --- |",
                ]
                for r in tarefas_rows(plan, com_dias=False, limite=12):
                    linhas.append(f"| {r[0]} | {r[1]} | {r[2]} |")
                if len(plan) > 12:
                    linhas.append(f"| … | … | +{len(plan) - 12} no kanban |")
                linhas.append("")
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
    alertas_hub = filtrar_alertas_hub(alertas_hub_raw)
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

    # —— Chatwoot (SÓ HOJE) ——
    linhas += ["", "---", "", "## 4. Chatwoot — reprocessamento do dia", ""]
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
    linhas += ["", "---", "", "## 5. Plano de ação consolidado", ""]
    linhas.append("_Prioridades derivadas do cruzamento Gestão por cliente + Hub + Chatwoot._")
    linhas.append("")
    for text, _tone in acoes_consolidadas(m):
        linhas.append(f"- {text}")

    # —— Fontes ——
    linhas += ["", "---", "", "## 6. Fontes e frescor", ""]
    for nome, info in fontes.items():
        if str(nome).lower() == "waha":
            continue
        if isinstance(info, dict):
            linhas.append(f"- {nome}: **{info.get('status')}**")
        else:
            linhas.append(f"- {nome}: {info}")
    for nome, bloco in (("Hub", painel), ("Chatwoot", cw)):
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
