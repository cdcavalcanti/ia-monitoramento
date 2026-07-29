"""Entrega WhatsApp via WAHA: 1 PDF + 1 mensagem (sem duplicar o relatório)."""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger("monitor.delivery")

# Evita reenvio acidental do mesmo stamp/arquivo na mesma rodada.
_ultimo_envio_key: str | None = None


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "X-Api-Key": s.waha_token,
        "Authorization": f"Bearer {s.waha_token}",
        "Content-Type": "application/json",
    }


def _chat_id() -> str | None:
    s = get_settings()
    if not s.delivery_whatsapp_enabled:
        return None
    chat_id = s.notify_whatsapp_to
    if not chat_id.endswith("@c.us") and chat_id.isdigit():
        chat_id = f"{chat_id}@c.us"
    return chat_id


async def _send_text(texto: str) -> bool:
    s = get_settings()
    chat_id = _chat_id()
    if not chat_id:
        logger.info("WhatsApp desligado (WAHA/NOTIFY_WHATSAPP_TO)")
        return False

    texto = re.sub(r"^#{1,6}\s*", "", texto.strip(), flags=re.MULTILINE)
    url = f"{s.waha_url}/api/sendText"
    body = {"session": s.waha_session, "chatId": chat_id, "text": texto}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=_headers(), json=body)
            resp.raise_for_status()
        return True
    except Exception:
        logger.exception("falha ao enviar WhatsApp via WAHA")
        return False


async def _send_file(path: Path, *, caption: str = "") -> bool:
    """Envia o PDF uma única vez (sem tentar 2 endpoints no mesmo sucesso)."""
    s = get_settings()
    chat_id = _chat_id()
    if not chat_id or not path.is_file():
        return False

    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    body = {
        "session": s.waha_session,
        "chatId": chat_id,
        "caption": (caption or path.name)[:200],
        "file": {
            "mimetype": "application/pdf",
            "filename": path.name,
            "data": b64,
        },
    }
    endpoints = [
        f"{s.waha_url}/api/sendFile",
        f"{s.waha_url}/api/send/file",
    ]
    last_err = ""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            for url in endpoints:
                resp = await client.post(url, headers=_headers(), json=body)
                if resp.status_code < 400:
                    return True
                last_err = f"{resp.status_code} {resp.text[:200]}"
                logger.warning("sendFile %s falhou: %s", url, last_err)
        logger.warning("nenhum endpoint sendFile aceitou o PDF (%s)", last_err)
        return False
    except Exception:
        logger.exception("falha ao enviar PDF via WAHA")
        return False


def _resumo_executivo(relatorio_md: str, *, limite: int = 900) -> str:
    """Só o bloco de resumo — não reenvia o relatório inteiro."""
    linhas = relatorio_md.splitlines()
    bullets: list[str] = []
    na_secao = False
    for line in linhas:
        if line.startswith("## 1.") or "Resumo executivo" in line:
            na_secao = True
            continue
        if na_secao and line.startswith("## "):
            break
        if na_secao and line.strip().startswith("- "):
            bullets.append(line.strip())
        if len(bullets) >= 10:
            break
    if not bullets:
        # fallback: primeiras linhas úteis
        for line in linhas:
            s = line.strip()
            if s.startswith("- "):
                bullets.append(s)
            if len(bullets) >= 8:
                break
    texto = "\n".join(bullets) if bullets else "(ver PDF)"
    if len(texto) > limite:
        texto = texto[: limite - 20].rsplit("\n", 1)[0] + "\n…"
    return texto


def _relatorio_completo_texto(relatorio_md: str, limite: int = 3500) -> str:
    texto = relatorio_md.strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    if "\n" in corte:
        corte = corte.rsplit("\n", 1)[0]
    return corte + "\n\n… (completo no servidor)"


async def enviar_whatsapp(
    relatorio_md: str,
    *,
    titulo: str = "Relatório — Infinity Monitor",
    pdf_path: Path | str | None = None,
) -> bool:
    """Uma entrega = no máximo 1 PDF + 1 texto (sem duplicar o corpo)."""
    global _ultimo_envio_key

    p = Path(pdf_path) if pdf_path else None
    key = f"{p.resolve() if p and p.is_file() else ''}|{titulo}|{hash(relatorio_md) & 0xFFFFFFFF:x}"
    if key == _ultimo_envio_key:
        logger.warning("envio duplicado ignorado (%s)", key)
        return True
    _ultimo_envio_key = key

    pdf_ok = False
    if p and p.is_file():
        # Caption curta — o detalhe vai na mensagem de texto, não de novo no PDF.
        pdf_ok = await _send_file(p, caption=titulo)
        if pdf_ok:
            logger.info("PDF enviado via WAHA")

    if pdf_ok:
        # Com PDF: mensagem curta (resumo), não o relatório inteiro de novo.
        corpo = (
            f"*{titulo}*\n"
            f"_Detalhes no PDF._\n\n"
            f"{_resumo_executivo(relatorio_md)}"
        )
    else:
        # Sem PDF: manda o texto completo (único canal).
        corpo = f"*{titulo}*\n\n{_relatorio_completo_texto(relatorio_md)}"

    ok = await _send_text(corpo)
    if ok:
        logger.info("mensagem WhatsApp enviada (pdf=%s)", pdf_ok)
    return bool(ok or pdf_ok)


async def enviar_alerta(texto: str, *, titulo: str = "Alerta — Infinity Monitor") -> bool:
    """Mensagem curta para queda de serviço / sessão WAHA / etc."""
    ok = await _send_text(f"*{titulo}*\n\n{texto.strip()}")
    if ok:
        logger.info("alerta enviado via WAHA")
    return ok
