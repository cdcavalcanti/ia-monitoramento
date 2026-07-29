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

    def section(self, title: str, accent=BLUE) -> None:
        p = self.pdf
        p.ln(3)
        if p.get_y() > 260:
            p.add_page()
        y = p.get_y()
        p.set_fill_color(*accent)
        p.rect(16, y + 0.5, 1.4, 6, "F")
        p.set_x(20)
        p.set_text_color(*NAVY)
        self._font(bold=True, size=12)
        p.cell(self.w - 4, 7, _safe(title), ln=1)
        p.set_draw_color(*LINE)
        p.set_line_width(0.2)
        p.line(16, p.get_y(), 16 + self.w, p.get_y())
        p.ln(2)
        p.set_text_color(*SLATE)

    def subsection(self, title: str) -> None:
        p = self.pdf
        p.ln(1.5)
        p.set_text_color(*MUTED)
        self._font(bold=True, size=9)
        p.cell(self.w, 5, _safe(title.upper()), ln=1)
        p.set_text_color(*SLATE)

    def para(self, text: str, *, size: float = 9.5, bold: bool = False) -> None:
        p = self.pdf
        self._font(bold=bold, size=size)
        p.multi_cell(self.w, 4.8, _safe(text))

    def bullet(self, text: str, *, tone: str | None = None) -> None:
        p = self.pdf
        colors = {
            "bad": RED,
            "warn": AMBER,
            "ok": GREEN,
            None: BLUE,
        }
        c = colors.get(tone, BLUE)
        x = p.l_margin
        y = p.get_y()
        if y > 275:
            p.add_page()
            y = p.get_y()
        p.set_fill_color(*c)
        p.ellipse(x + 1.2, y + 1.6, 1.6, 1.6, "F")
        p.set_xy(x + 5, y)
        self._font(size=9)
        p.set_text_color(*SLATE)
        p.multi_cell(self.w - 5, 4.6, _safe(text))

    def kpi_row(self, items: list[tuple[str, str, str]]) -> None:
        """items: (label, value, tone) tone in ok|warn|bad|info"""
        p = self.pdf
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
        for i, (label, value, tone) in enumerate(items):
            x = p.l_margin + i * (box_w + gap)
            p.set_fill_color(*fills.get(tone, BLUE_SOFT))
            p.set_draw_color(*LINE)
            p.rect(x, y, box_w, 16, "FD")
            p.set_xy(x + 2.5, y + 2)
            p.set_text_color(*MUTED)
            self._font(bold=True, size=7)
            p.cell(box_w - 5, 4, _safe(label.upper()))
            p.set_xy(x + 2.5, y + 7)
            p.set_text_color(*texts.get(tone, NAVY))
            self._font(bold=True, size=13)
            p.cell(box_w - 5, 6, _safe(str(value)))
        p.set_y(y + 18)
        p.set_text_color(*SLATE)

    def table(self, headers: list[str], rows: list[list[str]], *, col_weights: list[float] | None = None) -> None:
        p = self.pdf
        n = len(headers)
        weights = col_weights or [1] * n
        total_w = sum(weights)
        widths = [self.w * (w / total_w) for w in weights]

        # header
        p.set_fill_color(*NAVY_2)
        p.set_text_color(*WHITE)
        self._font(bold=True, size=8)
        x0 = p.l_margin
        y = p.get_y()
        for i, h in enumerate(headers):
            p.set_xy(x0 + sum(widths[:i]), y)
            p.cell(widths[i], 7, _safe(h), border=0, align="L" if i == 0 else "R", fill=True)
        p.set_y(y + 7)

        self._font(size=8.5)
        for r_i, row in enumerate(rows):
            y = p.get_y()
            if y > 275:
                p.add_page()
                y = p.get_y()
            bg = (248, 250, 252) if r_i % 2 == 0 else WHITE
            # highlight atrasado
            highlight = any("atrasad" in _safe(c).lower() for c in row)
            if highlight:
                bg = RED_SOFT
            p.set_fill_color(*bg)
            p.rect(x0, y, self.w, 6.5, "F")
            p.set_text_color(*NAVY if highlight else SLATE)
            for i, cell in enumerate(row):
                p.set_xy(x0 + sum(widths[:i]), y + 0.8)
                align = "L" if i == 0 else "R"
                self._font(bold=highlight and i == 1, size=8.5)
                p.cell(widths[i], 5, _safe(cell), align=align)
            p.set_y(y + 6.5)
        p.ln(2)
        p.set_text_color(*SLATE)

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
    """Gera PDF estilizado a partir do mesmo snapshot do dash/relatório."""
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        logger.warning("fpdf2 não instalado — pulando PDF")
        return None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    gestao = snapshot.get("gestao") if isinstance(snapshot.get("gestao"), dict) else {}
    painel = snapshot.get("painel") if isinstance(snapshot.get("painel"), dict) else {}
    cw = snapshot.get("chatwoot") if isinstance(snapshot.get("chatwoot"), dict) else {}
    waha = snapshot.get("waha") if isinstance(snapshot.get("waha"), dict) else {}
    repro = snapshot.get("reprocessamento") if isinstance(snapshot.get("reprocessamento"), dict) else {}
    fontes = snapshot.get("fontes") or {}
    alertas = list(snapshot.get("alertas") or [])
    tot = gestao.get("totais") if isinstance(gestao.get("totais"), dict) else {}
    kanban = tot.get("kanban") if isinstance(tot.get("kanban"), dict) else {}
    wt = waha.get("totais") if isinstance(waha.get("totais"), dict) else {}
    ct = cw.get("totais") if isinstance(cw.get("totais"), dict) else {}

    n_atr = int(_n(kanban.get("atrasado"), tot.get("atrasadas", 0)) or 0)
    n_hoje = int(_n(kanban.get("hoje"), tot.get("vencimento_hoje", 0)) or 0)
    n_working = int(_n(wt.get("working"), 0) or 0)
    n_ruins = int(_n(wt.get("ruins"), 0) or 0)
    elegiveis = list(cw.get("leads_elegiveis_reprocessamento") or cw.get("elegiveis") or [])
    n_el = int(ct.get("elegiveis") if ct.get("elegiveis") is not None else len(elegiveis))

    doc = RelatorioPDF()
    rotulo = snapshot.get("rotulo") or "manual"
    doc.header_band(
        "Relatorio operacional",
        f"Gerado {_fmt_quando(snapshot.get('gerado_em'))}  |  fuso America/Sao_Paulo  |  {rotulo}",
    )

    # KPIs topo
    doc.kpi_row(
        [
            ("Atrasadas", str(n_atr), "bad" if n_atr else "ok"),
            ("Vence hoje", str(n_hoje), "warn" if n_hoje else "ok"),
            ("WAHA OK", str(n_working), "ok" if n_working else "warn"),
            ("WAHA ruins", str(n_ruins), "bad" if n_ruins else "ok"),
            ("CW elegiveis", str(n_el), "warn" if n_el else "ok"),
        ]
    )

    # Resumo
    doc.section("1. Resumo executivo", BLUE)
    if alertas:
        for a in alertas[:12]:
            tone = "bad" if any(k in str(a).lower() for k in ("atrasad", "ruin", "failed", "offline")) else (
                "warn" if any(k in str(a).lower() for k in ("atencao", "elegiv", "parcial", "vence")) else None
            )
            doc.bullet(str(a), tone=tone)
    else:
        doc.bullet("Sem alertas no snapshot.", tone="ok")

    # Gestão
    doc.section("2. Gestao Infinity (kanban)", VIOLET)
    if tot:
        doc.para("Contagens por coluna do painel (igual ao Gestao).", size=8.5)
        rows = [
            ["Entrada de tarefas", str(_n(kanban.get("entrada"), 0))],
            ["Acompanhamento", str(_n(kanban.get("acompanhamento"), 0))],
            ["Atrasado", str(n_atr)],
            ["Vencimento hoje", str(n_hoje)],
            ["Vencimento amanha", str(_n(kanban.get("amanha"), tot.get("vencimento_amanha", 0)))],
            ["Vencimento essa semana", str(_n(kanban.get("semana"), tot.get("vencimento_semana", 0)))],
            ["Validacao", str(_n(kanban.get("validacao"), 0))],
            ["Aguardando cliente", str(_n(kanban.get("aguardando"), tot.get("aguardando_cliente", 0)))],
            ["Entregues (historico)", str(_n(kanban.get("entregues"), 0))],
        ]
        doc.table(["Coluna", "Qtd"], rows, col_weights=[3.2, 1])
        doc.para(f"Total de tarefas na API: {_n(tot.get('tarefas'))}.", size=8.5, bold=True)

        doc.subsection("Top atrasos")
        tops = list(gestao.get("atrasadas_top") or [])[:10]
        if tops:
            for t in tops:
                doc.bullet(
                    f"{t.get('cliente')} | {t.get('projeto')} | {t.get('titulo')} "
                    f"- {t.get('responsavel')} | {t.get('diasAtraso')}d",
                    tone="bad",
                )
        else:
            doc.bullet("Nenhuma tarefa na coluna Atrasado.", tone="ok")

        doc.subsection("Vencimento hoje")
        hoje = list(gestao.get("vencimento_hoje") or [])[:8]
        if hoje:
            for t in hoje:
                doc.bullet(
                    f"{t.get('cliente')} | {t.get('titulo')} - {t.get('responsavel')}",
                    tone="warn",
                )
        else:
            doc.bullet("Nenhum.", tone="ok")
    else:
        doc.bullet(f"Gestao indisponivel: {gestao.get('erro') or '-'}", tone="bad")

    # Hub
    doc.section("3. Hub de Status", AMBER)
    saude = (
        (painel.get("totais") or {}).get("saudeGeral")
        if isinstance(painel.get("totais"), dict)
        else None
    ) or painel.get("saudeGeral") or "-"
    tone_saude = "ok" if str(saude).lower() in ("ok", "saudavel", "saudável") else (
        "bad" if "crit" in str(saude).lower() else "warn"
    )
    doc.chip_row([(f"Saude: {saude}", tone_saude)])

    doc.subsection("Alertas do Hub")
    alertas_hub = list(painel.get("alertas_api") or [])
    if not alertas_hub:
        for a in painel.get("alertas") or []:
            if isinstance(a, dict):
                alertas_hub.append(a.get("texto") or a.get("log") or str(a))
            else:
                alertas_hub.append(str(a))
    if alertas_hub:
        for a in alertas_hub[:12]:
            doc.bullet(str(a), tone="warn")
    else:
        doc.bullet("Nenhum alerta.", tone="ok")

    doc.subsection("Clientes parcial / offline")
    clientes_p = list(painel.get("clientes_problema") or painel.get("clientes_com_problema") or [])[:18]
    if clientes_p:
        # grid compacto em chips
        chips = []
        for c in clientes_p:
            if isinstance(c, dict):
                nome = c.get("nome") or c.get("cliente") or "?"
                st = c.get("status") or c.get("estado") or "parcial"
                chips.append((f"{nome} ({st})", "warn"))
            else:
                chips.append((str(c), "warn"))
        doc.chip_row(chips)
    else:
        doc.bullet("Lista detalhada indisponivel; ver alertas acima.", tone="warn")

    # WAHA
    doc.section("4. WAHA (sessoes WhatsApp)", GREEN if not n_ruins else RED)
    doc.kpi_row(
        [
            ("WORKING", str(n_working), "ok"),
            ("Ruins", str(n_ruins), "bad" if n_ruins else "ok"),
            ("Total", str(_n(wt.get("total"), "-")), "info"),
        ]
    )
    ruins = list(waha.get("ruins") or [])[:18]
    if ruins:
        doc.subsection("Sessoes fora de WORKING")
        for s in ruins:
            if isinstance(s, dict):
                doc.bullet(f"{s.get('name') or s.get('nome')} > {s.get('status')}", tone="bad")
            else:
                doc.bullet(str(s), tone="bad")

    # Chatwoot
    doc.section("5. Chatwoot / silencio da IA", BLUE)
    n_pau = int(
        ct.get("pausados_com_silencio")
        if ct.get("pausados_com_silencio") is not None
        else len(cw.get("leads_pausados_ignorados") or cw.get("pausados") or [])
    )
    doc.kpi_row(
        [
            ("Elegiveis", str(n_el), "warn" if n_el else "ok"),
            ("Pausados", str(n_pau), "info"),
            ("Analisadas", str(_n(cw.get("conversas_analisadas"), "-")), "info"),
        ]
    )
    doc.subsection("Lista elegiveis (top)")
    if elegiveis:
        rows = []
        for x in elegiveis[:12]:
            if not isinstance(x, dict):
                continue
            rows.append(
                [
                    str(x.get("nome") or x.get("telefone") or "(sem nome)")[:28],
                    str(x.get("cliente") or x.get("account_nome") or "-")[:18],
                    str(x.get("conversation_id") or "-"),
                    f"{x.get('minutos_sem_resposta')} min",
                ]
            )
        if rows:
            doc.table(["Lead", "Cliente", "Conv", "Silencio"], rows, col_weights=[2.4, 1.6, 1, 1.2])
    else:
        doc.bullet("Nenhum elegivel no snapshot.", tone="ok")

    doc.subsection("Reprocessamento")
    doc.bullet(
        f"Deteccao ativa | envio auto: "
        f"{'ligado' if repro.get('automatico_habilitado') else 'desligado'} | "
        f"elegiveis: {_n(repro.get('elegiveis_detectados'), n_el)} | "
        f"status: {_n(repro.get('status'), '-')}"
    )

    # Ações
    doc.section("6. Acoes recomendadas", AMBER)
    acoes: list[tuple[str, str]] = []
    if n_atr:
        acoes.append((f"P0 - Triar as {n_atr} tarefas da coluna Atrasado.", "bad"))
    if n_hoje:
        acoes.append((f"P0 - Resolver {n_hoje} item(ns) com vencimento hoje.", "warn"))
    if n_el:
        acoes.append((f"P0 - Revisar {n_el} lead(s) Chatwoot elegiveis.", "warn"))
    if n_ruins:
        acoes.append((f"P1 - Recuperar sessoes WAHA ruins ({n_ruins}); WORKING={n_working}.", "bad"))
    if alertas_hub:
        acoes.append(("P1 - Conferir alertas do Hub.", "warn"))
    if not acoes:
        acoes.append(("Sem P0 automatico no snapshot.", "ok"))
    for text, tone in acoes:
        doc.bullet(text, tone=tone)

    # Fontes
    doc.section("7. Fontes", MUTED)
    chips = []
    for nome, info in fontes.items():
        st = info.get("status") if isinstance(info, dict) else str(info)
        tone = "ok" if st == "ok" else ("bad" if st == "erro" else "warn")
        chips.append((f"{nome}: {st}", tone))
    if chips:
        doc.chip_row(chips)

    doc.footer_note(
        "Relatorio montado a partir do snapshot (mesma base do dash). "
        "Numeros nao sao inventados por LLM. Infinity Monitor IA."
    )

    try:
        doc.pdf.output(str(destino))
    except Exception:
        logger.exception("falha ao gravar PDF")
        return None
    logger.info("PDF salvo em %s (%s bytes)", destino, destino.stat().st_size)
    return destino


def markdown_para_pdf(md: str, destino: Path) -> Path | None:
    """Compat: se só houver markdown, gera PDF simples estruturado."""
    # Extrai o que der do MD e usa um snapshot mínimo via parsing — ou layout básico.
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        return None

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = RelatorioPDF()
    doc.header_band("Relatorio operacional", "Gerado a partir do markdown")
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            doc.section(line[3:].strip())
            continue
        if line.startswith("### "):
            doc.subsection(line[4:].strip())
            continue
        if line.startswith("|"):
            continue
        if line.strip().startswith("- "):
            doc.bullet(line.strip()[2:])
            continue
        if line.startswith("_") and line.endswith("_"):
            continue
        doc.para(line, size=9)
    try:
        doc.pdf.output(str(destino))
        return destino
    except Exception:
        logger.exception("falha PDF markdown")
        return None
