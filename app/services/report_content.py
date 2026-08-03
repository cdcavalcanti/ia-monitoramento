"""Conteúdo consolidado do relatório — narrativa + cortes analíticos.

Números sempre vêm do snapshot (nunca inventados). Usado por MD e PDF.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _n(v: Any, default: int | str = 0) -> Any:
    return default if v is None else v


def sanear_chatwoot_somente_hoje(dados: dict[str, Any]) -> dict[str, Any]:
    """Garante elegíveis só do dia corrente — cache antigo não entra no relatório."""
    from app.collectors.chatwoot_health import filtrar_leads_somente_hoje, snapshot_eh_de_hoje
    from app.config import get_settings

    s = get_settings()
    out = dict(dados)
    only_today = bool(out.get("somente_hoje", True))
    if not only_today:
        return out

    atualizado = out.get("atualizado_em")
    if atualizado and not snapshot_eh_de_hoje(atualizado, tz_name=s.report_timezone):
        out["leads_elegiveis_reprocessamento"] = []
        if "elegiveis" in out:
            out["elegiveis"] = []
        totais = dict(out.get("totais") or {})
        totais["elegiveis"] = 0
        out["totais"] = totais
        out["aviso_dia"] = (
            f"Cache Chatwoot de outro dia ({atualizado}) — elegíveis zerados para o relatório de hoje."
        )
        for key in ("contas", "por_conta"):
            lista = out.get(key)
            if not isinstance(lista, list):
                continue
            out[key] = [
                {**c, "elegiveis": 0} if isinstance(c, dict) else c for c in lista
            ]
        return out

    eleg = list(out.get("leads_elegiveis_reprocessamento") or out.get("elegiveis") or [])
    filtrados = filtrar_leads_somente_hoje(eleg, tz_name=s.report_timezone)
    out["leads_elegiveis_reprocessamento"] = filtrados
    if "elegiveis" in out:
        out["elegiveis"] = filtrados
    totais = dict(out.get("totais") or {})
    totais["elegiveis"] = len(filtrados)
    out["totais"] = totais

    # Zera contagens por conta que não batem com leads filtrados do dia
    ids_hoje = {str(x.get("account_id")) for x in filtrados if isinstance(x, dict)}
    contagem = {}
    for x in filtrados:
        if not isinstance(x, dict):
            continue
        aid = str(x.get("account_id") or "")
        contagem[aid] = contagem.get(aid, 0) + 1
    for key in ("contas", "por_conta"):
        lista = out.get(key)
        if not isinstance(lista, list):
            continue
        novas = []
        for c in lista:
            if not isinstance(c, dict):
                continue
            cc = dict(c)
            aid = str(cc.get("account_id") or "")
            cc["elegiveis"] = int(contagem.get(aid, 0))
            novas.append(cc)
        out[key] = novas
    return out


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _gestao(snapshot: dict[str, Any]) -> dict[str, Any]:
    g = snapshot.get("gestao")
    return g if isinstance(g, dict) else {}


def _painel(snapshot: dict[str, Any]) -> dict[str, Any]:
    p = snapshot.get("painel")
    return p if isinstance(p, dict) else {}


def _cw(snapshot: dict[str, Any]) -> dict[str, Any]:
    c = snapshot.get("chatwoot")
    return c if isinstance(c, dict) else {}


def _waha(snapshot: dict[str, Any]) -> dict[str, Any]:
    """WAHA removido do monitor — mantido só por compat com snapshots antigos."""
    return {}


def metricas_base(snapshot: dict[str, Any]) -> dict[str, Any]:
    gestao = _gestao(snapshot)
    painel = _painel(snapshot)
    cw_raw = _cw(snapshot)
    cw = sanear_chatwoot_somente_hoje(cw_raw) if cw_raw else {}
    tot = gestao.get("totais") if isinstance(gestao.get("totais"), dict) else {}
    kanban = tot.get("kanban") if isinstance(tot.get("kanban"), dict) else {}
    ct = cw.get("totais") if isinstance(cw.get("totais"), dict) else {}

    elegiveis = list(cw.get("leads_elegiveis_reprocessamento") or cw.get("elegiveis") or [])
    pausados = list(cw.get("leads_pausados_ignorados") or cw.get("pausados") or [])
    n_el = len(elegiveis)
    n_pau = _int(ct.get("pausados_com_silencio"), len(pausados))
    n_atr = _int(kanban.get("atrasado"), _int(tot.get("atrasadas")))
    n_hoje = _int(kanban.get("hoje"), _int(tot.get("vencimento_hoje")))
    n_amanha = _int(kanban.get("amanha"), _int(tot.get("vencimento_amanha")))
    n_semana = _int(kanban.get("semana"), _int(tot.get("vencimento_semana")))
    n_aguard = _int(kanban.get("aguardando"), _int(tot.get("aguardando_cliente")))

    saude = (
        (painel.get("totais") or {}).get("saudeGeral")
        if isinstance(painel.get("totais"), dict)
        else None
    ) or painel.get("saudeGeral") or "-"

    clientes_hub = list(painel.get("clientes_problema") or painel.get("clientes_com_problema") or [])
    servicos = list(painel.get("servicos_problema") or painel.get("servicos") or [])

    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}
    n_repro_dia = _int(repro.get("enviados"), 0)
    n_clientes_ativos = len(gestao_por_cliente(gestao, limite=200))

    return {
        "gestao": gestao,
        "painel": painel,
        "cw": cw,
        "waha": {},
        "tot": tot,
        "kanban": kanban,
        "wt": {},
        "ct": ct,
        "n_atr": n_atr,
        "n_hoje": n_hoje,
        "n_amanha": n_amanha,
        "n_semana": n_semana,
        "n_aguard": n_aguard,
        "n_working": 0,
        "n_ruins": 0,
        "n_total_w": 0,
        "n_el": n_el,
        "n_pau": n_pau,
        "n_repro_dia": n_repro_dia,
        "n_clientes_ativos": n_clientes_ativos,
        "elegiveis": elegiveis,
        "pausados": pausados,
        "saude": saude,
        "clientes_hub": clientes_hub,
        "servicos": servicos,
        "repro": repro,
    }


def tabela_atrasos_detalhe(gestao: dict[str, Any], *, limite: int = 40) -> list[list[str]]:
    """Linhas: Cliente | Projeto | Responsável | Dias | Motivo | Tarefa."""
    tops = list(gestao.get("atrasadas_top") or [])[:limite]
    rows: list[list[str]] = []
    for t in tops:
        if not isinstance(t, dict):
            continue
        motivo = str(t.get("motivo") or "").strip() or "—"
        rows.append(
            [
                str(t.get("cliente") or "?")[:22],
                str(t.get("projeto") or "?")[:22],
                str(t.get("responsavel") or "?")[:20],
                f"{t.get('diasAtraso') or 0}d",
                motivo[:36],
                str(t.get("titulo") or "?")[:40],
            ]
        )
    return rows


def gestao_por_cliente(gestao: dict[str, Any], *, limite: int = 30) -> list[dict[str, Any]]:
    """Blocos já agregados por cliente (atrasos / hoje / semana)."""
    blocos = list(gestao.get("por_cliente") or [])
    out: list[dict[str, Any]] = []
    for b in blocos:
        if isinstance(b, dict):
            out.append(b)
        if len(out) >= limite:
            break
    if out:
        return out
    # Fallback: monta a partir das filas planas (snapshots antigos)
    return _gestao_por_cliente_fallback(gestao, limite=limite)


def _gestao_por_cliente_fallback(gestao: dict[str, Any], *, limite: int = 30) -> list[dict[str, Any]]:
    from collections import defaultdict

    bags: dict[str, dict[str, list]] = defaultdict(
        lambda: {
            "atrasadas": [],
            "vencimento_hoje": [],
            "vencimento_amanha": [],
            "vencimento_semana": [],
            "aguardando": [],
            "projetos": set(),
        }
    )

    def _push(chave: str, itens: list[Any]) -> None:
        for t in itens or []:
            if not isinstance(t, dict):
                continue
            nome = str(t.get("cliente") or "?").strip() or "?"
            bags[nome][chave].append(t)
            proj = str(t.get("projeto") or "").strip()
            if proj:
                bags[nome]["projetos"].add(proj)

    _push("atrasadas", list(gestao.get("atrasadas_top") or []))
    _push("vencimento_hoje", list(gestao.get("vencimento_hoje") or []))
    _push("vencimento_amanha", list(gestao.get("vencimento_amanha") or []))
    _push("vencimento_semana", list(gestao.get("vencimento_semana") or []))
    _push("aguardando", list(gestao.get("aguardando_cliente") or []))

    # Se não veio atrasadas_top, espalha atrasos_por_cliente
    if not any(bags[n]["atrasadas"] for n in bags):
        por = gestao.get("atrasos_por_cliente")
        if isinstance(por, dict):
            for nome, itens in por.items():
                if not isinstance(itens, list):
                    continue
                for t in itens:
                    if isinstance(t, dict):
                        bags[str(nome)]["atrasadas"].append(t)
                        proj = str(t.get("projeto") or "").strip()
                        if proj:
                            bags[str(nome)]["projetos"].add(proj)

    result: list[dict[str, Any]] = []
    for nome, bloco in bags.items():
        n_atr = len(bloco["atrasadas"])
        n_hoje = len(bloco["vencimento_hoje"])
        n_amanha = len(bloco["vencimento_amanha"])
        n_semana = len(bloco["vencimento_semana"])
        n_aguard = len(bloco["aguardando"])
        if not (n_atr or n_hoje or n_amanha or n_semana or n_aguard):
            continue
        plan = (
            list(bloco["vencimento_hoje"])
            + list(bloco["vencimento_amanha"])
            + list(bloco["vencimento_semana"])
        )
        result.append(
            {
                "cliente": nome,
                "projetos": sorted(bloco["projetos"]),
                "atrasadas": bloco["atrasadas"][:25],
                "vencimento_hoje": bloco["vencimento_hoje"][:20],
                "vencimento_amanha": bloco["vencimento_amanha"][:15],
                "vencimento_semana": bloco["vencimento_semana"][:20],
                "aguardando": bloco["aguardando"][:10],
                "planejamento_semana": plan[:30],
                "metricas": {
                    "atrasadas": n_atr,
                    "hoje": n_hoje,
                    "amanha": n_amanha,
                    "semana": n_semana,
                    "aguardando": n_aguard,
                    "projetos": len(bloco["projetos"]),
                },
            }
        )
    result.sort(
        key=lambda c: (
            -int((c.get("metricas") or {}).get("atrasadas") or 0),
            -int((c.get("metricas") or {}).get("hoje") or 0),
            str(c.get("cliente") or ""),
        )
    )
    return result[:limite]


def _tarefa_row_curta(t: dict[str, Any], *, com_dias: bool = False) -> list[str]:
    proj = str(t.get("projeto") or "?")[:28]
    resp = str(t.get("responsavel") or "?")[:20]
    titulo = str(t.get("titulo") or "?")[:48]
    if com_dias:
        return [proj, resp, f"{t.get('diasAtraso') or 0}d", titulo]
    return [proj, resp, titulo]


def tarefas_rows(itens: list[Any], *, com_dias: bool = False, limite: int = 15) -> list[list[str]]:
    rows: list[list[str]] = []
    for t in list(itens or [])[:limite]:
        if isinstance(t, dict):
            rows.append(_tarefa_row_curta(t, com_dias=com_dias))
    return rows



def scorecard_dominios(m: dict[str, Any]) -> list[dict[str, str]]:
    """Estado por domínio para o panorama."""
    rows: list[dict[str, str]] = []

    # Gestão
    if m["n_atr"] >= 5 or m["n_hoje"] >= 5:
        st, det = "critico", f"{m['n_atr']} atrasada(s), {m['n_hoje']} vence hoje"
    elif m["n_atr"] or m["n_hoje"] or m["n_amanha"]:
        st, det = "atencao", f"{m['n_atr']} atrasada(s), {m['n_hoje']} hoje, {m['n_amanha']} amanha"
    else:
        st, det = "ok", "Sem atrasos nem vencimento critico no kanban"
    rows.append({"dominio": "Gestao (kanban)", "estado": st, "destaque": det})

    # Hub
    saude = str(m["saude"]).lower()
    n_cli = len(m["clientes_hub"])
    n_svc = len([s for s in m["servicos"] if isinstance(s, dict) and str(s.get("nivel") or "") != "ok"])
    if "crit" in saude or n_cli >= 10:
        st, det = "critico", f"saude {m['saude']} | {n_cli} cliente(s) parcial/offline"
    elif "aten" in saude or n_cli or n_svc:
        st, det = "atencao", f"saude {m['saude']} | {n_cli} cliente(s), {n_svc} servico(s)"
    else:
        st, det = "ok", f"saude {m['saude']}"
    rows.append({"dominio": "Hub de Status", "estado": st, "destaque": det})

    # Chatwoot
    if m["n_el"] >= 8:
        st, det = "critico", f"{m['n_el']} elegiveis a reprocessar | {m['n_pau']} pausados"
    elif m["n_el"]:
        st, det = "atencao", f"{m['n_el']} elegiveis | {m['n_pau']} pausados"
    else:
        st, det = "ok", f"Sem elegiveis | {m['n_pau']} pausados"
    rows.append({"dominio": "Chatwoot / IA", "estado": st, "destaque": det})

    return rows


def panorama_paragrafos(m: dict[str, Any]) -> list[str]:
    """Leitura consolidada em prosa (determinística)."""
    gestao = m["gestao"]
    por_cli = gestao.get("atrasos_por_cliente") if isinstance(gestao.get("atrasos_por_cliente"), dict) else {}
    por_resp = (
        gestao.get("atrasos_por_responsavel")
        if isinstance(gestao.get("atrasos_por_responsavel"), dict)
        else {}
    )

    top_cli = sorted(por_cli.items(), key=lambda kv: -len(kv[1] if isinstance(kv[1], list) else []))[:3]
    top_resp = list(por_resp.items())[:3] if por_resp else []

    p1_parts = [
        f"Panorama do periodo: Gestao com {m['n_atr']} tarefa(s) atrasada(s), "
        f"{m['n_hoje']} com vencimento hoje, {m['n_amanha']} amanha e {m['n_semana']} na semana"
        f" ({m['n_aguard']} aguardando cliente) — "
        f"{m.get('n_clientes_ativos') or 0} cliente(s) com fila ativa."
    ]
    if top_cli:
        cli_txt = ", ".join(f"{nome} ({len(itens)})" for nome, itens in top_cli if isinstance(itens, list))
        p1_parts.append(f"Atrasos concentrados em: {cli_txt}.")
    if top_resp:
        resp_txt = ", ".join(f"{nome} ({qtd})" for nome, qtd in top_resp)
        p1_parts.append(f"Responsaveis com mais atraso: {resp_txt}.")

    p2 = (
        f"Operacao de canais: Hub em '{m['saude']}' com {len(m['clientes_hub'])} cliente(s) "
        f"parcial/offline; Chatwoot com {m['n_el']} lead(s) elegivel(is) a reprocessar "
        f"(somente silencio de hoje) e {m['n_pau']} pausado(s)/handoff."
    )

    # Contas CW quentes
    contas = list(m["cw"].get("contas") or m["cw"].get("por_conta") or [])
    quentes = sorted(
        [c for c in contas if isinstance(c, dict) and _int(c.get("elegiveis")) > 0],
        key=lambda c: _int(c.get("elegiveis")),
        reverse=True,
    )[:4]
    p3 = ""
    if quentes:
        bits = [
            f"{c.get('account_nome') or c.get('cliente') or c.get('account_id')} "
            f"({_int(c.get('elegiveis'))})"
            for c in quentes
        ]
        p3 = "Foco Chatwoot por conta: " + ", ".join(bits) + "."

    out = [" ".join(p1_parts), p2]
    if p3:
        out.append(p3)
    return out


def atrasos_por_cliente_rows(gestao: dict[str, Any], *, limite: int = 10) -> list[list[str]]:
    por = gestao.get("atrasos_por_cliente") if isinstance(gestao.get("atrasos_por_cliente"), dict) else {}
    rows: list[list[str]] = []
    for nome, itens in sorted(por.items(), key=lambda kv: -len(kv[1] if isinstance(kv[1], list) else []))[
        :limite
    ]:
        if not isinstance(itens, list):
            continue
        dias = []
        for it in itens:
            try:
                dias.append(int(it.get("diasAtraso") or 0))
            except (TypeError, ValueError):
                pass
        max_d = max(dias) if dias else 0
        titulos = "; ".join(str(it.get("titulo") or "?")[:40] for it in itens[:3])
        if len(itens) > 3:
            titulos += f" (+{len(itens) - 3})"
        rows.append([str(nome)[:28], str(len(itens)), f"{max_d}d", titulos[:70]])
    return rows


def atrasos_por_resp_rows(gestao: dict[str, Any], *, limite: int = 8) -> list[list[str]]:
    por = gestao.get("atrasos_por_responsavel")
    if not isinstance(por, dict):
        return []
    return [[str(n)[:32], str(q)] for n, q in list(por.items())[:limite]]


def waha_por_status(waha: dict[str, Any]) -> list[tuple[str, int]]:
    ruins = list(waha.get("ruins") or [])
    c: Counter[str] = Counter()
    for s in ruins:
        if isinstance(s, dict):
            c[str(s.get("status") or "UNKNOWN").upper()] += 1
        else:
            c["UNKNOWN"] += 1
    return c.most_common()


def contas_cw_rows(cw: dict[str, Any], *, so_com_sinal: bool = True) -> list[list[str]]:
    contas = list(cw.get("contas") or cw.get("por_conta") or [])
    rows: list[list[str]] = []
    for c in contas:
        if not isinstance(c, dict):
            continue
        el = _int(c.get("elegiveis"))
        pau = _int(c.get("pausados_com_silencio"))
        anal = _int(c.get("conversas_analisadas"))
        if so_com_sinal and el == 0 and pau == 0 and not c.get("skipped") and not c.get("erro"):
            continue
        nome = str(c.get("account_nome") or c.get("cliente") or c.get("account_id") or "?")[:22]
        flag = "skip" if c.get("skipped") else ("erro" if c.get("erro") else "ok")
        rows.append([nome, str(el), str(pau), str(anal), flag])
    rows.sort(key=lambda r: -int(r[1] or 0))
    return rows


def acoes_consolidadas(m: dict[str, Any]) -> list[tuple[str, str]]:
    """Ações com contexto (não só contagem genérica)."""
    acoes: list[tuple[str, str]] = []
    gestao = m["gestao"]
    por_resp = (
        gestao.get("atrasos_por_responsavel")
        if isinstance(gestao.get("atrasos_por_responsavel"), dict)
        else {}
    )
    por_cli = gestao.get("atrasos_por_cliente") if isinstance(gestao.get("atrasos_por_cliente"), dict) else {}

    if m["n_atr"]:
        top_r = list(por_resp.items())[:2]
        extra = ""
        if top_r:
            extra = " | foco: " + ", ".join(f"{n} ({q})" for n, q in top_r)
        top_c = sorted(por_cli.items(), key=lambda kv: -len(kv[1] if isinstance(kv[1], list) else []))[:2]
        if top_c:
            extra += " | clientes: " + ", ".join(
                f"{n} ({len(v)})" for n, v in top_c if isinstance(v, list)
            )
        acoes.append((f"P0 Gestao — Triar {m['n_atr']} atrasada(s){extra}.", "bad"))

    if m["n_hoje"]:
        hoje = list(gestao.get("vencimento_hoje") or [])[:3]
        nomes = ", ".join(
            f"{t.get('cliente')}/{t.get('titulo')}"[:40] for t in hoje if isinstance(t, dict)
        )
        suf = f" Ex.: {nomes}." if nomes else ""
        acoes.append((f"P0 Gestao — Fechar {m['n_hoje']} item(ns) com vencimento hoje.{suf}", "warn"))

    if m["n_el"]:
        contas = contas_cw_rows(m["cw"], so_com_sinal=True)
        foco = ", ".join(f"{r[0]} ({r[1]})" for r in contas[:3] if _int(r[1]) > 0)
        suf = f" Contas: {foco}." if foco else ""
        acoes.append(
            (f"P0 Chatwoot — Revisar {m['n_el']} elegivel(is) (somente hoje){suf}", "warn")
        )

    if m["clientes_hub"]:
        amostra = []
        for c in m["clientes_hub"][:4]:
            if isinstance(c, dict):
                amostra.append(str(c.get("nome") or c.get("cliente") or "?"))
            else:
                amostra.append(str(c))
        acoes.append(
            (
                f"P1 Hub — Checar {len(m['clientes_hub'])} cliente(s) parcial/offline"
                + (f" ({', '.join(amostra)}…)" if amostra else "."),
                "warn",
            )
        )

    if m["n_amanha"] or m["n_semana"]:
        acoes.append(
            (
                f"P2 Gestao — Antecipar fila: {m['n_amanha']} amanha + {m['n_semana']} esta semana.",
                "info",
            )
        )

    if not acoes:
        acoes.append(("Sem P0 automatico — operacao dentro do esperado no snapshot.", "ok"))
    return acoes
