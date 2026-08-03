"""PDF do relatório — layout Infinity (navy + azul céu), tipografia limpa."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("monitor.report_pdf")

# Paleta alinhada ao dash / Gestão Infinity
NAVY = (12, 18, 32)
NAVY_2 = (17, 24, 39)
BLUE = (14, 165, 233)
BLUE_SOFT = (224, 242, 254)
SLATE = (51, 65, 85)
MUTED = (100, 116, 139)
LINE = (226, 232, 240)
WHITE = (255, 255, 255)
RED = (239, 68, 68)
RED_SOFT = (254, 226, 226)
AMBER = (245, 158, 11)
AMBER_SOFT = (254, 243, 199)
GREEN = (34, 197, 94)
GREEN_SOFT = (220, 252, 231)
VIOLET = (139, 92, 246)


def _safe(text: Any) -> str:
    s = "" if text is None else str(text)
    s = (
        s.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2022", "-")
        .replace("\u00a0", " ")
        .replace("\u2192", ">")
        .replace("·", "|")
        .replace("≥", ">=")
    )
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _fmt_quando(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo("America/Sao_Paulo"))
        return local.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return _safe(iso)[:19]


def _carimbo_cabecalho(snapshot: dict[str, Any]) -> tuple[str, str]:
    """(dia_br, gerado_br) — dia de HOJE no fuso SP no momento da geração do PDF."""
    from app.services.tempo import carimbo_relatorio, hoje_br

    agora = carimbo_relatorio()
    return hoje_br(), agora["gerado_em_br"]


def _n(v: Any, default: int | str = 0) -> Any:
    return default if v is None else v


class RelatorioPDF:
    def __init__(self) -> None:
        from fpdf import FPDF

        self.pdf = FPDF(format="A4", unit="mm")
        self.pdf.set_auto_page_break(auto=True, margin=18)
        self.pdf.set_margins(16, 16, 16)
        self._setup_fonts()
        self.pdf.add_page()
        self.w = self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def _setup_fonts(self) -> None:
        # Windows: Segoe UI / Arial — português ok em latin-1
        candidates = [
            (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
            (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
            (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf"),
        ]
        self.font = "Helvetica"
        self.font_b = "Helvetica"
        for regular, bold in candidates:
            if Path(regular).is_file() and Path(bold).is_file():
                try:
                    self.pdf.add_font("Inf", "", regular)
                    self.pdf.add_font("Inf", "B", bold)
                    self.font = "Inf"
                    self.font_b = "Inf"
                    return
                except Exception:
                    continue

    def _font(self, *, bold: bool = False, size: float = 10) -> None:
        family = self.font
        style = "B" if bold else ""
        self.pdf.set_font(family, style, size)

    def header_band(self, titulo: str, subtitulo: str) -> None:
        p = self.pdf
        y0 = p.get_y()
        p.set_fill_color(*NAVY)
        p.rect(0, 0, p.w, 32, "F")
        p.set_fill_color(*BLUE)
        p.rect(0, 32, p.w, 1.2, "F")
        p.set_xy(16, 8)
        p.set_text_color(*BLUE)
        self._font(bold=True, size=9)
        p.cell(self.w, 5, _safe("INFINITY MONITOR IA"))
        p.set_xy(16, 14)
        p.set_text_color(*WHITE)
        self._font(bold=True, size=16)
        p.cell(self.w, 8, _safe(titulo))
        p.set_xy(16, 23)
        p.set_text_color(148, 163, 184)
        self._font(size=8.5)
        p.cell(self.w, 5, _safe(subtitulo))
        p.set_y(max(y0, 38))
        p.set_text_color(*SLATE)

    def _page_bottom(self) -> float:
        return self.pdf.h - 18

    def ensure_space(self, needed_mm: float) -> None:
        """Quebra página antes se não couber título+conteúdo mínimo (anti-órfão)."""
        p = self.pdf
        if p.get_y() + needed_mm > self._page_bottom():
            p.add_page()

    def section(self, title: str, accent=BLUE, *, keep_with_mm: float = 42) -> None:
        p = self.pdf
        p.ln(2)
        # seção + bloco mínimo de conteúdo (anti-órfão / anti-split)
        self.ensure_space(10 + keep_with_mm)
        y = p.get_y()
        p.set_fill_color(*accent)
        p.rect(16, y + 0.5, 1.4, 6, "F")
        p.set_x(20)
        p.set_text_color(*NAVY)
        self._font(bold=True, size=12)
        p.cell(self.w - 4, 7, _safe(title), new_x="LMARGIN", new_y="NEXT")
        p.set_draw_color(*LINE)
        p.set_line_width(0.2)
        p.line(16, p.get_y(), 16 + self.w, p.get_y())
        p.ln(2)
        p.set_text_color(*SLATE)

    def subsection(self, title: str, *, keep_with_mm: float = 30) -> None:
        """Subtítulo que não fica sozinho no rodapé — leva o 1º bloco junto."""
        p = self.pdf
        p.ln(1.5)
        self.ensure_space(6 + keep_with_mm)
        p.set_text_color(*MUTED)
        self._font(bold=True, size=9)
        p.set_x(p.l_margin)
        p.cell(self.w, 5, _safe(title.upper()), new_x="LMARGIN", new_y="NEXT")
        p.set_text_color(*SLATE)

    def para(self, text: str, *, size: float = 9.5, bold: bool = False) -> None:
        p = self.pdf
        if p.get_y() > 270:
            p.add_page()
        p.set_x(p.l_margin)
        self._font(bold=bold, size=size)
        p.set_text_color(*SLATE)
        p.multi_cell(self.w, 4.8, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text: str, *, tone: str | None = None) -> None:
        p = self.pdf
        colors = {
            "bad": RED,
            "warn": AMBER,
            "ok": GREEN,
            None: BLUE,
        }
        c = colors.get(tone, BLUE)
        if p.get_y() > 270:
            p.add_page()
        x = p.l_margin
        y = p.get_y()
        p.set_fill_color(*c)
        p.ellipse(x + 1.2, y + 1.6, 1.6, 1.6, "F")
        p.set_xy(x + 5, y)
        self._font(size=9)
        p.set_text_color(*SLATE)
        p.multi_cell(self.w - 5, 4.6, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def kpi_row(self, items: list[tuple[str, str, str]]) -> None:
        """items: (label, value, tone) tone in ok|warn|bad|info"""
        p = self.pdf
        if p.get_y() > 260:
            p.add_page()
        n = max(1, len(items))
        gap = 2.5
        box_w = (self.w - gap * (n - 1)) / n
        y = p.get_y()
        fills = {
            "ok": GREEN_SOFT,
            "warn": AMBER_SOFT,
            "bad": RED_SOFT,
            "info": BLUE_SOFT,
        }
        texts = {
            "ok": GREEN,
            "warn": (180, 83, 9),
            "bad": RED,
            "info": (3, 105, 161),
        }
        p.set_auto_page_break(auto=False)
        try:
            for i, (label, value, tone) in enumerate(items):
                x = p.l_margin + i * (box_w + gap)
                p.set_fill_color(*fills.get(tone, BLUE_SOFT))
                p.set_draw_color(*LINE)
                p.rect(x, y, box_w, 16, "FD")
                p.set_xy(x + 2.5, y + 2)
                p.set_text_color(*MUTED)
                self._font(bold=True, size=6.5)
                p.cell(
                    box_w - 5,
                    4,
                    self._fit_text(label.upper(), box_w - 5, size=6.5, bold=True),
                    new_x="RIGHT",
                    new_y="TOP",
                )
                p.set_xy(x + 2.5, y + 7)
                p.set_text_color(*texts.get(tone, NAVY))
                self._font(bold=True, size=13)
                p.cell(
                    box_w - 5,
                    6,
                    self._fit_text(str(value), box_w - 5, size=13, bold=True),
                    new_x="RIGHT",
                    new_y="TOP",
                )
        finally:
            p.set_auto_page_break(auto=True, margin=18)
        p.set_y(y + 18)
        p.set_text_color(*SLATE)

    def _fit_text(self, text: str, width: float, *, size: float = 8.5, bold: bool = False) -> str:
        """Corta texto para caber na coluna (evita page-break do fpdf2)."""
        self._font(bold=bold, size=size)
        t = _safe(text)
        max_w = max(2.0, width - 1.2)
        if self.pdf.get_string_width(t) <= max_w:
            return t
        ell = "..."
        while t and self.pdf.get_string_width(t + ell) > max_w:
            t = t[:-1]
        return (t + ell) if t else ""

    def table(self, headers: list[str], rows: list[list[str]], *, col_weights: list[float] | None = None) -> None:
        """Tabela estável: sem page-break no meio da linha; texto truncado à coluna."""
        p = self.pdf
        if not headers:
            return
        n = len(headers)
        weights = list(col_weights or [1.0] * n)
        if len(weights) < n:
            weights.extend([1.0] * (n - len(weights)))
        weights = weights[:n]
        total_w = sum(weights) or 1.0
        widths = [self.w * (w / total_w) for w in weights]
        x0 = p.l_margin
        row_h = 6.5
        head_h = 7.0

        # Tabelas com 6+ cols: cards. Até 5 cols cabem em tabela A4.
        if n >= 6:
            self._table_cards(headers, rows)
            return

        self.ensure_space(head_h + row_h + 4)

        def draw_header() -> None:
            y = p.get_y()
            if y + head_h > self._page_bottom():
                p.add_page()
                y = p.get_y()
            p.set_fill_color(*NAVY_2)
            p.set_text_color(*WHITE)
            self._font(bold=True, size=7.5)
            x = x0
            for i, h in enumerate(headers):
                p.set_xy(x, y)
                p.cell(
                    widths[i],
                    head_h,
                    self._fit_text(h, widths[i], size=7.5, bold=True),
                    border=0,
                    fill=True,
                    align="L",
                    new_x="RIGHT",
                    new_y="TOP",
                )
                x += widths[i]
            p.set_y(y + head_h)
            p.set_text_color(*SLATE)

        # Desliga page-break automático durante a tabela (senão cada cell vira página).
        p.set_auto_page_break(auto=False)
        try:
            draw_header()
            for r_i, row in enumerate(rows):
                if p.get_y() + row_h > self._page_bottom():
                    p.add_page()
                    draw_header()
                y = p.get_y()
                cells = list(row) + [""] * n
                cells = cells[:n]
                bg = (248, 250, 252) if r_i % 2 == 0 else WHITE
                if any("atrasad" in _safe(c).lower() for c in cells):
                    bg = RED_SOFT
                p.set_fill_color(*bg)
                p.rect(x0, y, self.w, row_h, "F")
                p.set_text_color(*SLATE)
                x = x0
                for i, cell in enumerate(cells):
                    p.set_xy(x, y + 0.8)
                    self._font(size=8)
                    p.cell(
                        widths[i],
                        row_h - 1.2,
                        self._fit_text(cell, widths[i], size=8),
                        border=0,
                        align="L",
                        new_x="RIGHT",
                        new_y="TOP",
                    )
                    x += widths[i]
                p.set_y(y + row_h)
        finally:
            p.set_auto_page_break(auto=True, margin=18)
        p.ln(2)
        p.set_text_color(*SLATE)

    def _table_cards(self, headers: list[str], rows: list[list[str]]) -> None:
        """Cards compactos para tabelas largas — sempre mostra Motivo/Dias/Tarefa."""
        p = self.pdf
        self.ensure_space(24)
        card_h_est = 16.0
        for row in rows:
            if p.get_y() + card_h_est > self._page_bottom():
                p.add_page()
            cells = list(row) + [""] * len(headers)
            cells = cells[: len(headers)]
            y0 = p.get_y()
            p.set_fill_color(*LINE)
            p.rect(p.l_margin, y0, self.w, 0.4, "F")
            p.ln(1.8)

            # Linha 1: Cliente · Projeto · Responsável
            destaque = " · ".join(
                _safe(cells[i]).strip()
                for i in range(min(3, len(headers)))
                if _safe(cells[i]).strip()
            )
            if destaque:
                self._font(bold=True, size=9)
                p.set_text_color(*NAVY)
                p.set_x(p.l_margin)
                p.multi_cell(
                    self.w,
                    4.2,
                    self._fit_text(destaque, self.w, size=9, bold=True),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

            # Linha 2: campos restantes (Dias, Motivo, Tarefa…) — nunca omite Motivo
            extras: list[str] = []
            for i in range(3, len(headers)):
                label = headers[i]
                raw = cells[i] if i < len(cells) else ""
                val = _safe(raw).strip() if raw is not None else ""
                if not val:
                    val = "-"
                extras.append(f"{label}: {val}")
            if extras:
                self._font(size=8)
                p.set_text_color(*SLATE)
                p.set_x(p.l_margin)
                p.multi_cell(
                    self.w,
                    3.8,
                    self._fit_text(" | ".join(extras), self.w, size=8),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            p.ln(1.0)
        p.set_text_color(*SLATE)
        p.ln(0.5)
    def chip_row(self, chips: list[tuple[str, str]]) -> None:
        """chips: (text, tone)"""
        p = self.pdf
        x = p.l_margin
        y = p.get_y()
        fills = {"ok": GREEN_SOFT, "warn": AMBER_SOFT, "bad": RED_SOFT, "info": BLUE_SOFT}
        texts = {"ok": GREEN, "warn": (180, 83, 9), "bad": RED, "info": (3, 105, 161)}
        for text, tone in chips:
            label = _safe(text)
            self._font(bold=True, size=8)
            tw = p.get_string_width(label) + 6
            if x + tw > p.l_margin + self.w:
                y += 8
                x = p.l_margin
                if y > 275:
                    p.add_page()
                    y = p.get_y()
                    x = p.l_margin
            p.set_fill_color(*fills.get(tone, BLUE_SOFT))
            p.set_xy(x, y)
            p.set_text_color(*texts.get(tone, NAVY))
            p.cell(tw, 6.5, label, fill=True, align="C")
            x += tw + 2.5
        p.set_y(y + 9)
        p.set_text_color(*SLATE)

    def footer_note(self, text: str) -> None:
        p = self.pdf
        p.ln(4)
        p.set_draw_color(*LINE)
        p.line(16, p.get_y(), 16 + self.w, p.get_y())
        p.ln(2)
        p.set_text_color(*MUTED)
        self._font(size=7.5)
        p.multi_cell(self.w, 3.8, _safe(text))


def snapshot_para_pdf(snapshot: dict[str, Any], destino: Path) -> Path | None:
    """Gera PDF consolidado a partir do mesmo snapshot do dash/relatório."""
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        logger.warning("fpdf2 não instalado — pulando PDF")
        return None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    from app.services.report_content import (
        acoes_consolidadas,
        contas_cw_rows,
        gestao_por_cliente,
        metricas_base,
        panorama_paragrafos,
        scorecard_dominios,
        tarefas_rows,
    )
    from app.services.report_md import (
        alerta_hub_waha_desatualizado,
        criticidade_alerta,
        filtrar_alertas_hub,
        ordenar_alertas_por_criticidade,
    )

    m = metricas_base(snapshot)
    gestao, painel, cw = m["gestao"], m["painel"], m["cw"]
    tot = m["tot"]
    fontes = snapshot.get("fontes") or {}
    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}

    alertas = [
        a
        for a in ordenar_alertas_por_criticidade(list(snapshot.get("alertas") or []))
        if not alerta_hub_waha_desatualizado(a)
    ]

    doc = RelatorioPDF()
    rotulo = snapshot.get("rotulo") or "manual"
    dia_br, gerado_br = _carimbo_cabecalho(snapshot)
    doc.header_band(
        "Relatorio operacional consolidado",
        f"HOJE {dia_br}  |  Gerado {gerado_br}  |  fuso America/Sao_Paulo  |  {rotulo}",
    )

    # KPIs topo
    doc.kpi_row(
        [
            ("Atrasadas", str(m["n_atr"]), "bad" if m["n_atr"] else "ok"),
            ("Vence hoje", str(m["n_hoje"]), "warn" if m["n_hoje"] else "ok"),
            ("Na semana", str(m["n_semana"]), "info"),
            ("Clientes", str(m.get("n_clientes_ativos") or 0), "info"),
            ("CW elegiveis", str(m["n_el"]), "warn" if m["n_el"] else "ok"),
        ]
    )

    # —— 1. Panorama consolidado ——
    doc.section("1. Panorama consolidado", BLUE)
    for p in panorama_paragrafos(m):
        doc.para(p, size=9.5)

    doc.subsection("Scorecard por dominio")
    sc = scorecard_dominios(m)
    sc_rows = []
    for row in sc:
        sc_rows.append([row["dominio"], row["estado"].upper(), row["destaque"][:78]])
    doc.table(["Dominio", "Estado", "Destaque"], sc_rows, col_weights=[1.6, 1.0, 3.2])

    doc.subsection("Sinais por criticidade")
    if alertas:
        for a in alertas[:12]:
            nivel = criticidade_alerta(a)
            tone = {0: "bad", 1: "warn", 2: "warn", 3: None}.get(nivel)
            doc.bullet(str(a), tone=tone)
    else:
        doc.bullet("Sem alertas agregados no snapshot.", tone="ok")

    # —— 2. Gestão por cliente ——
    doc.section("2. Gestao por cliente", VIOLET)
    if tot:
        doc.para(
            f"Kanban: {m['n_atr']} atrasada(s) · {m['n_hoje']} hoje · {m['n_amanha']} amanha · "
            f"{m['n_semana']} semana · {m['n_aguard']} aguardando · "
            f"{m.get('n_clientes_ativos') or 0} cliente(s) ativos "
            f"(API {_n(tot.get('tarefas'))} tarefas).",
            size=8.5,
            bold=True,
        )
        blocos = gestao_por_cliente(gestao, limite=20)
        if not blocos:
            doc.bullet("Nenhum cliente com fila ativa no snapshot.", tone="ok")
        for bloco in blocos:
            met = bloco.get("metricas") or {}
            nome = str(bloco.get("cliente") or "?")
            projetos = list(bloco.get("projetos") or [])
            n_atr_c = int(met.get("atrasadas") or 0)
            doc.subsection(
                f"{nome}  |  {n_atr_c} atrasada(s) · {met.get('hoje', 0)} hoje · "
                f"{met.get('semana', 0)} semana",
                keep_with_mm=36,
            )
            doc.para(
                f"Projetos: {', '.join(projetos[:8]) if projetos else '—'}"
                + (f" (+{len(projetos) - 8})" if len(projetos) > 8 else ""),
                size=8,
            )
            doc.chip_row(
                [
                    (f"Atrasadas: {met.get('atrasadas', 0)}", "bad" if n_atr_c else "ok"),
                    (f"Hoje: {met.get('hoje', 0)}", "warn" if met.get("hoje") else "ok"),
                    (f"Amanha: {met.get('amanha', 0)}", "info"),
                    (f"Semana: {met.get('semana', 0)}", "info"),
                    (f"Aguardando: {met.get('aguardando', 0)}", "info"),
                ]
            )

            atr = list(bloco.get("atrasadas") or [])
            if atr:
                doc.para("ATRASADAS — resolver", size=8.5, bold=True)
                doc.table(
                    ["Projeto", "Responsavel", "Dias", "Tarefa"],
                    tarefas_rows(atr, com_dias=True, limite=12),
                    col_weights=[1.4, 1.2, 0.55, 2.2],
                )

            plan = list(bloco.get("planejamento_semana") or [])
            if plan:
                doc.para("Planejamento da semana (hoje · amanha · semana)", size=8.5, bold=True)
                doc.table(
                    ["Projeto", "Responsavel", "Tarefa"],
                    tarefas_rows(plan, com_dias=False, limite=10),
                    col_weights=[1.5, 1.3, 2.5],
                )
                if len(plan) > 10:
                    doc.para(f"+{len(plan) - 10} no kanban deste cliente.", size=7.5)
    else:
        doc.bullet(f"Gestao indisponivel: {gestao.get('erro') or '-'}", tone="bad")

    # —— 3. Hub ——
    doc.section("3. Hub de Status", AMBER, keep_with_mm=40)
    tone_saude = (
        "ok"
        if str(m["saude"]).lower() in ("ok", "saudavel", "saudável")
        else ("bad" if "crit" in str(m["saude"]).lower() else "warn")
    )
    doc.chip_row(
        [
            (f"Saude: {m['saude']}", tone_saude),
            (f"Clientes problema: {len(m['clientes_hub'])}", "warn" if m["clientes_hub"] else "ok"),
            (f"Servicos problema: {len(m['servicos'])}", "warn" if m["servicos"] else "ok"),
        ]
    )

    doc.subsection("Alertas do Hub")
    alertas_hub_raw = list(painel.get("alertas_api") or [])
    if not alertas_hub_raw:
        for a in painel.get("alertas") or []:
            alertas_hub_raw.append(a)
    alertas_hub = filtrar_alertas_hub(alertas_hub_raw)
    if alertas_hub:
        for a in alertas_hub[:14]:
            doc.bullet(str(a), tone="warn")
    else:
        doc.bullet("Nenhum alerta relevante do Hub.", tone="ok")

    doc.subsection("Servicos com problema")
    servicos = [s for s in m["servicos"] if isinstance(s, dict)][:16]
    if servicos:
        doc.table(
            ["Servico", "Tipo", "Status", "Nivel"],
            [
                [
                    str(s.get("nome") or "?")[:28],
                    str(s.get("tipo") or "-")[:14],
                    str(s.get("status") or "-")[:16],
                    str(s.get("nivel") or "-")[:10],
                ]
                for s in servicos
            ],
            col_weights=[2.0, 1.2, 1.4, 1.0],
        )
    else:
        doc.bullet("Nenhum servico critico listado no snapshot.", tone="ok")

    doc.subsection("Clientes parcial / offline")
    if m["clientes_hub"]:
        chips = []
        for c in m["clientes_hub"][:24]:
            if isinstance(c, dict):
                nome = c.get("nome") or c.get("cliente") or "?"
                st = c.get("status") or c.get("estado") or "parcial"
                chips.append((f"{nome} ({st})", "warn"))
            else:
                chips.append((str(c), "warn"))
        doc.chip_row(chips)
    else:
        doc.bullet("Lista detalhada indisponivel; ver alertas acima.", tone="warn")

    if painel.get("atualizado_em") or painel.get("origem"):
        doc.para(
            f"Hub origem: {painel.get('origem') or 'coleta'} | atualizado {_fmt_quando(painel.get('atualizado_em'))}",
            size=8,
        )

    # —— 4. Chatwoot SÓ HOJE ——
    doc.section("4. Chatwoot — reprocessamento do dia", BLUE, keep_with_mm=58)
    limiar = _n(cw.get("silencio_minutos"), 5)
    doc.kpi_row(
        [
            ("Elegiveis HOJE", str(m["n_el"]), "warn" if m["n_el"] else "ok"),
            ("Reprocessados HOJE", str(m.get("n_repro_dia", 0)), "ok"),
            ("Pausados/handoff", str(m["n_pau"]), "info"),
        ]
    )
    if cw.get("aviso_dia"):
        doc.bullet(
            "Sem varredura fresca de hoje — lista zerada (nao usa lead de dia anterior).",
            tone="warn",
        )
    else:
        doc.para(f"Regra: incoming de hoje · s/ resposta >= {limiar:g} min · sem pausa/handoff.", size=8)

    doc.subsection("Contas com elegiveis hoje", keep_with_mm=22)
    crows = [r for r in contas_cw_rows(cw, so_com_sinal=True) if r[1] != "0"]
    if crows:
        doc.table(
            ["Conta", "Elegiveis hoje"],
            [[r[0], r[1]] for r in crows[:12]],
            col_weights=[3.0, 1.2],
        )
    else:
        doc.bullet("Nenhuma conta com elegivel hoje.", tone="ok")

    doc.subsection("Leads elegiveis hoje", keep_with_mm=28)
    if m["elegiveis"]:
        rows = []
        for x in m["elegiveis"][:20]:
            if not isinstance(x, dict):
                continue
            rows.append(
                [
                    str(x.get("nome") or x.get("telefone") or "?")[:22],
                    str(x.get("cliente") or x.get("account_nome") or "-")[:14],
                    str(x.get("conversation_id") or "-"),
                    f"{x.get('minutos_sem_resposta')} min",
                    _fmt_quando(x.get("ultimo_incoming_em")) if x.get("ultimo_incoming_em") else "-",
                ]
            )
        doc.table(
            ["Lead", "Conta", "Id", "S/ resp", "Incoming"],
            rows,
            col_weights=[1.8, 1.2, 0.9, 1.0, 1.4],
        )
    else:
        doc.bullet("Nenhum elegivel hoje.", tone="ok")

    doc.subsection("Lote (hoje)", keep_with_mm=16)
    doc.bullet(
        f"Auto: {'ligado' if repro.get('automatico_habilitado') else 'desligado'} | "
        f"elegiveis {m['n_el']} | enviados {m.get('n_repro_dia', 0)} | "
        f"status {_n(repro.get('status'), '-')}"
    )

    # —— 5. Ações ——
    doc.section("5. Plano de acao consolidado", AMBER)
    doc.para(
        "Prioridades derivadas do cruzamento Gestao por cliente + Hub + Chatwoot.",
        size=8.5,
    )
    for text, tone in acoes_consolidadas(m):
        doc.bullet(text, tone=tone if tone != "info" else None)

    # —— 6. Fontes ——
    doc.section("6. Fontes e frescor", MUTED)
    chips = []
    for nome, info in fontes.items():
        if str(nome).lower() == "waha":
            continue
        st = info.get("status") if isinstance(info, dict) else str(info)
        tone = "ok" if st == "ok" else ("bad" if st == "erro" else "warn")
        chips.append((f"{nome}: {st}", tone))
    if chips:
        doc.chip_row(chips)
    for nome, bloco, chave in (
        ("Gestao", gestao, None),
        ("Hub", painel, "atualizado_em"),
        ("Chatwoot", cw, "atualizado_em"),
    ):
        when = bloco.get(chave) if chave and isinstance(bloco, dict) else None
        origem = bloco.get("origem") if isinstance(bloco, dict) else None
        if when or origem:
            doc.bullet(
                f"{nome}: {_fmt_quando(when) if when else '-'} | origem {origem or 'coleta'}"
            )

    doc.footer_note(
        "Relatorio consolidado a partir do snapshot (mesma base do dash). "
        "Numeros nao sao inventados por LLM. Infinity Monitor IA."
    )

    try:
        doc.pdf.output(str(destino))
    except Exception:
        logger.exception("falha ao gravar PDF")
        return None
    logger.info("PDF salvo em %s (%s bytes)", destino, destino.stat().st_size)
    return destino


def relatorio_para_pdf(
    relatorio_md: str,
    snapshot: dict[str, Any],
    destino: Path,
) -> Path | None:
    """PDF do relatório enriquecido pela IA (Markdown) + KPIs do snapshot.

    O corpo vem do texto da Infinity Lab / OpenAI. Os KPIs do topo são
    âncoras determinísticas do snapshot (mesmos números do dash).
    """
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        logger.warning("fpdf2 não instalado — pulando PDF")
        return None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    from app.services.report_content import metricas_base

    m = metricas_base(snapshot)
    doc = RelatorioPDF()
    rotulo = snapshot.get("rotulo") or "manual"
    dia_br, gerado_br = _carimbo_cabecalho(snapshot)
    doc.header_band(
        "Relatorio operacional consolidado",
        f"HOJE {dia_br}  |  Gerado {gerado_br}  |  fuso America/Sao_Paulo  |  {rotulo}  |  sintese IA",
    )
    doc.kpi_row(
        [
            ("Atrasadas", str(m["n_atr"]), "bad" if m["n_atr"] else "ok"),
            ("Vence hoje", str(m["n_hoje"]), "warn" if m["n_hoje"] else "ok"),
            ("Na semana", str(m["n_semana"]), "info"),
            ("Clientes", str(m.get("n_clientes_ativos") or 0), "info"),
            ("CW elegiveis", str(m["n_el"]), "warn" if m["n_el"] else "ok"),
        ]
    )
    doc.para(
        "Corpo abaixo sintetizado pela IA de Monitoramento (Infinity Lab), "
        "ancorada nos numeros oficiais do snapshot.",
        size=8,
    )

    _render_markdown_body(doc, relatorio_md or "")

    doc.footer_note(
        "Sintese pela IA Infinity Lab (fallback OpenAI/base factual). "
        "KPIs do topo = snapshot deterministico. Infinity Monitor IA."
    )
    try:
        doc.pdf.output(str(destino))
    except Exception:
        logger.exception("falha ao gravar PDF (relatorio IA)")
        return None
    logger.info("PDF (IA) salvo em %s (%s bytes)", destino, destino.stat().st_size)
    return destino


def _parse_md_table(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int]:
    """Lê tabela Markdown a partir de `start`. Retorna (headers, rows, next_index)."""
    headers = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    i = start + 1
    if i < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", lines[i]):
        i += 1
    rows: list[list[str]] = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        # ignora separator residual
        if all(re.match(r"^:?-+:?$", c or "") for c in cells):
            i += 1
            continue
        while len(cells) < len(headers):
            cells.append("")
        rows.append(cells[: len(headers)])
        i += 1
    return headers, rows, i


def _tone_from_bullet(text: str) -> str | None:
    t = text.lower()
    if any(k in t for k in ("p0", "atrasad", "failed", "crít", "critico", "ruin")):
        return "bad"
    if any(k in t for k in ("p1", "aten", "elegiv", "vence", "parcial", "warn")):
        return "warn"
    if any(k in t for k in ("p2", "ok", "sem p0", "nenhum")):
        return "ok"
    return None


def _render_markdown_body(doc: RelatorioPDF, md: str) -> None:
    """Renderiza Markdown da IA no PDF (seções, bullets, tabelas, parágrafos)."""
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped or stripped == "---":
            i += 1
            continue

        # pula título H1 (já temos header band)
        if stripped.startswith("# ") and not stripped.startswith("## "):
            i += 1
            continue

        if stripped.startswith("## "):
            title = stripped[3:].strip()
            accent = BLUE
            low = title.lower()
            if "gest" in low:
                accent = VIOLET
            elif "hub" in low or "painel" in low:
                accent = AMBER
            elif "waha" in low:
                accent = GREEN
            elif "chatwoot" in low or "resposta" in low or "reprocess" in low:
                accent = BLUE
            elif "acao" in low or "ação" in low or "plano" in low:
                accent = AMBER
            elif "fonte" in low:
                accent = MUTED
            doc.section(title, accent)
            i += 1
            continue

        if stripped.startswith("### "):
            doc.subsection(stripped[4:].strip())
            i += 1
            continue

        if stripped.startswith("|") and stripped.count("|") >= 2:
            headers, rows, nxt = _parse_md_table(lines, i)
            # Ignora tabela vazia / só cabeçalho (gera páginas fantasmas)
            if headers and rows:
                n = len(headers)
                if n >= 5:
                    weights = None  # cards
                elif n == 4:
                    weights = [1.4, 1.4, 1.4, 1.0]
                elif n == 3:
                    weights = [1.6, 1.0, 2.2]
                elif n == 2:
                    weights = [3.0, 1.0]
                else:
                    weights = [1.0]
                doc.table(headers, rows[:40], col_weights=weights)
            i = nxt
            continue

        if stripped.startswith(("- ", "* ", "• ")):
            text = stripped[2:].strip()
            # ignora nota meta sobre alerta WAHA
            if "waha" in text.lower() and "não configur" in text.lower().replace("nao configur", "não configur"):
                i += 1
                continue
            if "ignorado alerta" in text.lower():
                i += 1
                continue
            doc.bullet(text, tone=_tone_from_bullet(text))
            i += 1
            continue

        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) < 80:
            doc.para(stripped.strip("*"), size=9.5, bold=True)
            i += 1
            continue

        if stripped.startswith("_") and stripped.endswith("_"):
            doc.para(stripped.strip("_"), size=8)
            i += 1
            continue

        doc.para(stripped, size=9.5)
        i += 1


def markdown_para_pdf(md: str, destino: Path) -> Path | None:
    """Compat: Markdown puro → PDF (sem KPIs de snapshot)."""
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        return None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = RelatorioPDF()
    doc.header_band("Relatorio operacional consolidado", "Gerado a partir do markdown da IA")
    _render_markdown_body(doc, md)
    doc.footer_note("Renderizado a partir do Markdown sintetizado pela IA. Infinity Monitor IA.")
    try:
        doc.pdf.output(str(destino))
        return destino
    except Exception:
        logger.exception("falha PDF markdown")
        return None
