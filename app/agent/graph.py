"""Agente LangGraph — síntese do relatório + modo Q&A.

A geração diária NÃO usa tools: o snapshot já vem pronto do pipeline
(agregação determinística). O ReAct com tools serve para perguntas
posteriores sobre o que foi gerado.
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

logger = logging.getLogger("monitor.agent")

_agent = None
_saver_cm = None
_llm_sintese = None


def _state_modifier(state):
    return [SystemMessage(content=build_system_prompt())] + state["messages"]


async def get_agent():
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
    logger.info("agente Q&A pronto (modelo=%s)", s.openai_chat_model)
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


async def sintetizar_relatorio(snapshot: dict[str, Any]) -> str:
    """Gera o Markdown do relatório a partir do snapshot agregado."""
    s = get_settings()
    if not s.openai_api_key:
        return _fallback_sem_llm(snapshot)

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    # guarda-tamanho: snapshot pode ser grande; o aggregator já corta top-N
    if len(snapshot_json) > 140000:
        snapshot_json = snapshot_json[:140000] + "\n…(truncado)"

    msgs = [
        SystemMessage(content=build_system_prompt()),
        HumanMessage(content=build_user_prompt(snapshot_json)),
    ]
    resp = await _llm().ainvoke(msgs)
    texto = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
    if not texto:
        return _fallback_sem_llm(snapshot)
    return texto


async def perguntar(thread_id: str, pergunta: str) -> str:
    """Modo interativo: pergunta sobre o último relatório (com tools)."""
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


def _fallback_sem_llm(snapshot: dict[str, Any]) -> str:
    """Se não houver OPENAI_API_KEY, ainda assim entrega relatório estruturado."""
    alertas = snapshot.get("alertas") or []
    fontes = snapshot.get("fontes") or {}
    gestao = snapshot.get("gestao") or {}
    totais = gestao.get("totais") if isinstance(gestao, dict) else None

    linhas = [
        "# Relatório diário — Infinity Monitor",
        "",
        f"_Gerado em {snapshot.get('gerado_em')}_",
        "",
        "## 1. Resumo executivo",
    ]
    if alertas:
        linhas.extend(f"- {a}" for a in alertas)
    else:
        linhas.append("- Sem alertas registrados.")

    linhas += ["", "## 2. Gestão Infinity — Projetos e tarefas"]
    if totais:
        linhas.append(
            f"- Tarefas: {totais.get('tarefas')} | Atrasadas: {totais.get('atrasadas')} | "
            f"Em dev: {totais.get('em_desenvolvimento')} | Vence hoje: {totais.get('vencimento_hoje')} | "
            f"Aguardando cliente: {totais.get('aguardando_cliente')}"
        )
        for t in (gestao.get("atrasadas_top") or [])[:15]:
            linhas.append(
                f"- ATRASO: {t.get('cliente')} · {t.get('projeto')} · {t.get('titulo')} "
                f"({t.get('responsavel')}, {t.get('diasAtraso')}d)"
            )
    elif isinstance(gestao, dict) and gestao.get("erro"):
        linhas.append(f"- Erro na fonte: {gestao.get('erro')}")
    else:
        linhas.append("- Gestão indisponível ou sem dados.")

    linhas += ["", "## 3. Painel de Serviços"]
    painel = snapshot.get("painel") or {}
    linhas.append(f"- {painel.get('aviso') or painel.get('erro') or painel}")

    linhas += ["", "## 4. Chatwoot / IAs de atendimento"]
    cw = snapshot.get("chatwoot") or {}
    linhas.append(f"- {cw.get('aviso') or cw.get('erro') or cw}")

    linhas += ["", "## 5. Ações recomendadas para hoje"]
    if totais and totais.get("atrasadas"):
        linhas.append("- P0: Triar tarefas atrasadas listadas acima.")
    if totais and totais.get("vencimento_hoje"):
        linhas.append("- P0: Fechar ou renegociar itens com vencimento hoje.")
    linhas.append("- P2: Conectar Painel e Chatwoot quando as APIs chegarem.")

    linhas += ["", "## 6. Fontes e lacunas"]
    for nome, info in fontes.items():
        if isinstance(info, dict):
            linhas.append(f"- {nome}: {info.get('status')}")

    linhas += [
        "",
        "_Nota: OPENAI_API_KEY ausente — relatório em modo fallback (sem síntese LLM)._",
    ]
    return "\n".join(str(x) for x in linhas)
