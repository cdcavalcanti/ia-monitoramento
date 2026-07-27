"""Tools do agente de monitoramento.

Mesmo padrão do realdeal-sdr:
1. Identidade/contexto não vem como telefone — aqui o contexto é o snapshot
   do dia, injetado no prompt do turno.
2. Validação devolve prosa, não stack trace.

Na geração diária o pipeline já coleta tudo e só pede síntese ao LLM.
As tools abaixo servem ao modo interativo (perguntas sobre o último relatório)
e a regenerações pontuais sem reabrir o pipeline inteiro.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from app.services import store

logger = logging.getLogger("monitor.tools")


@tool
async def obter_ultimo_snapshot() -> str:
    """Retorna o snapshot JSON do último relatório gerado (ou avisa se não houver)."""
    dados = store.carregar_ultimo()
    if not dados:
        return "nenhum relatório gerado ainda. Peça para rodar o pipeline diário."
    snap = dados.get("snapshot") or {}
    # compacta: não devolve markdown junto
    try:
        return json.dumps(snap, ensure_ascii=False, default=str)[:120000]
    except Exception:
        logger.exception("falha ao serializar snapshot")
        return "não consegui ler o snapshot agora."


@tool
async def obter_ultimo_relatorio() -> str:
    """Retorna o markdown do último relatório diário salvo."""
    dados = store.carregar_ultimo()
    if not dados:
        return "nenhum relatório gerado ainda."
    md = dados.get("relatorio_md") or ""
    if not md:
        return "arquivo existe mas está sem markdown."
    return md[:50000]


@tool
async def resumir_alertas() -> str:
    """Lista os alertas do último snapshot de forma objetiva."""
    dados = store.carregar_ultimo()
    if not dados:
        return "nenhum relatório gerado ainda."
    snap: dict[str, Any] = dados.get("snapshot") or {}
    alertas = snap.get("alertas") or []
    fontes = snap.get("fontes") or {}
    linhas = ["Alertas:"]
    if alertas:
        linhas.extend(f"- {a}" for a in alertas)
    else:
        linhas.append("- (nenhum alerta registrado)")
    linhas.append("Fontes:")
    for nome, info in fontes.items():
        if isinstance(info, dict):
            linhas.append(f"- {nome}: {info.get('status')}")
    return "\n".join(linhas)


TOOLS = [obter_ultimo_snapshot, obter_ultimo_relatorio, resumir_alertas]
