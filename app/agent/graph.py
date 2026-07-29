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
    """Gera o Markdown do relatório a partir do snapshot agregado."""
    s = get_settings()
    user_content = build_user_prompt(_snapshot_json(snapshot))
    conv = conversation_id or f"relatorio-{(snapshot.get('rotulo') or 'diario')}"

    if s.infinity_lab_enabled:
        try:
            texto = await infinity_lab.chat(content=user_content, conversation_id=conv, purpose="relatorio")
            if texto:
                return texto
        except Exception:
            logger.exception("Infinity Lab falhou na síntese — tentando fallback")

    if s.openai_api_key:
        try:
            msgs = [
                SystemMessage(content=build_system_prompt()),
                HumanMessage(content=user_content),
            ]
            resp = await _llm().ainvoke(msgs)
            texto = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
            if texto:
                usage = {}
                meta = getattr(resp, "usage_metadata", None) or getattr(resp, "response_metadata", {}) or {}
                if isinstance(meta, dict):
                    usage = meta.get("token_usage") or meta.get("usage") or {}
                    if not usage and ("input_tokens" in meta or "output_tokens" in meta):
                        usage = meta
                from app.services import metrics as metrics_svc

                metrics_svc.record_llm_from_texts(
                    provider="openai",
                    purpose="relatorio",
                    prompt=user_content,
                    completion=texto,
                    usage=usage if isinstance(usage, dict) else {},
                    ok=True,
                )
                return texto
        except Exception:
            logger.exception("OpenAI falhou na síntese — usando fallback estruturado")
            try:
                from app.services import metrics as metrics_svc

                metrics_svc.record_llm_from_texts(
                    provider="openai",
                    purpose="relatorio",
                    prompt=user_content,
                    completion="",
                    ok=False,
                )
            except Exception:
                pass

    return _fallback_sem_llm(snapshot)


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


def _fallback_sem_llm(snapshot: dict[str, Any]) -> str:
    """Sem Lab/OpenAI — relatório estruturado."""
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

    linhas += ["", "## 3. Hub de Status"]
    painel = snapshot.get("painel") or {}
    if isinstance(painel, dict):
        tot_p = painel.get("totais") or {}
        linhas.append(f"- Saúde geral: {tot_p.get('saudeGeral') or painel.get('aviso') or painel.get('erro') or '—'}")
        for a in (painel.get("alertas_api") or [])[:8]:
            linhas.append(f"- Hub: {a}")
    else:
        linhas.append(f"- {painel}")

    linhas += ["", "## 4. Chatwoot / IAs de atendimento"]
    cw = snapshot.get("chatwoot") or {}
    if isinstance(cw, dict):
        tot_c = cw.get("totais") or {}
        linhas.append(
            f"- Elegíveis reprocessar: {tot_c.get('elegiveis')} | "
            f"Pausados: {tot_c.get('pausados_com_silencio')} | "
            f"{cw.get('aviso') or cw.get('erro') or ''}"
        )
    else:
        linhas.append(f"- {cw}")

    linhas += ["", "## 5. Ações recomendadas para hoje"]
    if totais and totais.get("atrasadas"):
        linhas.append("- P0: Triar tarefas atrasadas listadas acima.")
    if totais and totais.get("vencimento_hoje"):
        linhas.append("- P0: Fechar ou renegociar itens com vencimento hoje.")
    linhas.append("- P1: Revisar alertas do Hub de Status.")

    linhas += ["", "## 6. Fontes e lacunas"]
    for nome, info in fontes.items():
        if isinstance(info, dict):
            linhas.append(f"- {nome}: {info.get('status')}")

    linhas += [
        "",
        "_Nota: sem Infinity Lab/OpenAI — relatório em modo fallback (sem síntese LLM)._",
    ]
    return "\n".join(str(x) for x in linhas)
