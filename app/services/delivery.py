"""Entrega WhatsApp via WAHA: relatórios longos + alertas curtos."""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger("monitor.delivery")


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
    headers = {"Authorization": f"Bearer {s.waha_token}", "Content-Type": "application/json"}
    body = {"session": s.waha_session, "chatId": chat_id, "text": texto}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
        return True
    except Exception:
        logger.exception("falha ao enviar WhatsApp via WAHA")
        return False


def _resumo_whatsapp(relatorio_md: str, limite: int = 3500) -> str:
    texto = relatorio_md.strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    if "\n" in corte:
        corte = corte.rsplit("\n", 1)[0]
    return corte + "\n\n… (relatório completo salvo no servidor)"


async def enviar_whatsapp(relatorio_md: str, *, titulo: str = "Relatório — Infinity Monitor") -> bool:
    ok = await _send_text(f"*{titulo}*\n\n" + _resumo_whatsapp(relatorio_md))
    if ok:
        logger.info("relatório enviado via WAHA")
    return ok


async def enviar_alerta(texto: str, *, titulo: str = "Alerta — Infinity Monitor") -> bool:
    """Mensagem curta para queda de serviço / sessão WAHA / etc."""
    ok = await _send_text(f"*{titulo}*\n\n{texto.strip()}")
    if ok:
        logger.info("alerta enviado via WAHA")
    return ok
