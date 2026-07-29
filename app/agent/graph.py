"""Agente — síntese do relatório + Q&A.

Prioridade:
  1) Infinity Lab (agente na GPU própria — Gemma 3 27B configurado na plataforma)
  2) OpenAI (fallback legado)
  3) Fallback estruturado sem LLM
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.prompts import build_system_prompt, build_user_prompt
from app.agent.tools import TOOLS
from app.config import get_settings
from app.services import infinity_lab, store

logger = logging.getLogger("monitor.agent")

_agent = None
_saver_cm = None
_llm_sintese = None


def _state_modifier(state):
    return [SystemMessage(content=build_system_prompt())] + state["messages"]


async def get_agent():
    """ReAct local (OpenAI) — só se Lab estiver off e OpenAI on."""
    global _agent, _saver_cm
    if _agent is not None:
        return _agent

    s = get_settings()
    s.ensure_dirs()

    memoria = str(s.sqlite_path).replace(".db", "_memory.db")
    _saver_cm = AsyncSqliteSaver.from_conn_string(memoria)
    checkpointer = await _saver_cm.__aenter__()

    llm = ChatOpenAI(
        model=s.openai_chat_model,
        temperature=0.2,
        api_key=s.openai_api_key,
    )

    _agent = create_react_agent(
        llm,
        TOOLS,
        state_modifier=_state_modifier,
        checkpointer=checkpointer,
    )
    logger.info("agente Q&A OpenAI pronto (modelo=%s)", s.openai_chat_model)
    return _agent


def _llm() -> ChatOpenAI:
    global _llm_sintese
    if _llm_sintese is None:
        s = get_settings()
        _llm_sintese = ChatOpenAI(
            model=s.openai_chat_model,
            temperature=0.2,
            api_key=s.openai_api_key,
        )
    return _llm_sintese


def _snapshot_json(snapshot: dict[str, Any]) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    # Gemma 27B aguenta contexto grande, mas o aggregator já corta top-N.
    if len(snapshot_json) > 100000:
        snapshot_json = snapshot_json[:100000] + "\n…(truncado)"
    return snapshot_json


async def sintetizar_relatorio(snapshot: dict[str, Any], *, conversation_id: str = "") -> str:
    """Relatório diário: template determinístico (mesmos números do dash).

    Lab/OpenAI não recalculam totais — só poluem quando inventam. Mantemos
    o Markdown estruturado a partir do snapshot agregado.
    """
    from app.services.report_md import montar_relatorio

    return montar_relatorio(snapshot)


def _fallback_sem_llm(snapshot: dict[str, Any]) -> str:
    from app.services.report_md import montar_relatorio

    return montar_relatorio(snapshot)


async def perguntar(thread_id: str, pergunta: str) -> str:
    """Pergunta sobre o último relatório."""
    s = get_settings()

    if s.infinity_lab_enabled:
        # Injeta o último relatório no turno (o Lab já tem system prompt + RAG).
        ultimo = store.carregar_ultimo() or {}
        md = (ultimo.get("relatorio_md") or "")[:40000]
        alertas = (ultimo.get("snapshot") or {}).get("alertas") or []
        contexto = ""
        if md:
            contexto = (
                "Contexto — último relatório salvo:\n\n"
                f"{md}\n\n"
                f"Alertas: {alertas}\n\n"
                "---\n"
                f"Pergunta: {pergunta}"
            )
        else:
            contexto = (
                "Ainda não há relatório salvo localmente. "
                f"Pergunta: {pergunta}"
            )
        try:
            return await infinity_lab.chat(
                content=contexto,
                conversation_id=thread_id or "ops",
                purpose="perguntar",
            )
        except Exception:
            logger.exception("Infinity Lab falhou no Q&A")
            if not s.openai_api_key:
                return "não consegui consultar o Infinity Lab agora."

    if not s.openai_api_key:
        return "nenhum motor LLM configurado (Infinity Lab ou OPENAI_API_KEY)."

    agent = await get_agent()
    config = {"configurable": {"thread_id": thread_id}}
    resultado = await agent.ainvoke(
        {"messages": [HumanMessage(content=pergunta)]},
        config=config,
    )
    mensagens = resultado.get("messages", [])
    for m in reversed(mensagens):
        if m.__class__.__name__ == "AIMessage" and isinstance(m.content, str) and m.content.strip():
            return m.content.strip()
    return "(sem resposta)"
