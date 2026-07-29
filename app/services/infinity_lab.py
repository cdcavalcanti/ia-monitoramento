"""Cliente do Infinity Lab — agentes na GPU própria (Ollama / Gemma / Qwen).

POST /v1/agents/{id}/chat
Authorization: Bearer <inf_...>

O system prompt e o conhecimento ficam no agente da plataforma.
Aqui só mandamos a mensagem do usuário (+ conversation_id).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services import metrics

logger = logging.getLogger("monitor.infinity_lab")


def _extrair_texto(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return str(payload).strip()

    for key in ("response", "content", "resposta", "text", "output", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            inner = val.get("content") or val.get("text") or val.get("response")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"].strip()

    data = payload.get("data")
    if isinstance(data, dict):
        return _extrair_texto(data)

    return ""


def _extrair_usage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("usage", "token_usage", "tokens"):
        u = payload.get(key)
        if isinstance(u, dict):
            return u
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("usage"), dict):
        return data["usage"]
    return {}


async def chat(
    *,
    content: str,
    conversation_id: str,
    stream: bool = False,
    timeout: float = 180.0,
    purpose: str = "chat",
) -> str:
    """Envia uma mensagem ao agente de monitoramento no Lab."""
    s = get_settings()
    if not s.infinity_lab_enabled:
        raise RuntimeError("Infinity Lab não configurado (INFINITY_LAB_API_KEY / AGENT_ID)")

    url = (
        f"{s.infinity_lab_base_url.rstrip('/')}"
        f"/v1/agents/{s.infinity_lab_agent_id}/chat"
    )
    headers = {
        "Authorization": f"Bearer {s.infinity_lab_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "conversation_id": conversation_id,
        "messages": [{"role": "user", "content": content}],
        "stream": stream,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        texto = _extrair_texto(data)
        usage = _extrair_usage(data)
        if not texto:
            logger.warning(
                "resposta Lab sem texto parseável: keys=%s",
                list(data.keys()) if isinstance(data, dict) else type(data),
            )
            metrics.record_llm_from_texts(
                provider="infinity_lab",
                purpose=purpose,
                prompt=content,
                completion="",
                usage=usage,
                ok=False,
            )
            raise RuntimeError("Infinity Lab retornou resposta vazia/inesperada")

        metrics.record_llm_from_texts(
            provider="infinity_lab",
            purpose=purpose,
            prompt=content,
            completion=texto,
            usage=usage,
            ok=True,
        )
        return texto
    except RuntimeError:
        raise
    except Exception:
        try:
            metrics.record_llm_from_texts(
                provider="infinity_lab",
                purpose=purpose,
                prompt=content,
                completion="",
                ok=False,
            )
        except Exception:
            pass
        raise
