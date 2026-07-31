"""Agente — síntese do relatório + Q&A.

Prioridade:
  1) Infinity Lab (agente na GPU própria — Gemma 3 27B configurado na plataforma)
  2) OpenAI (fallback legado)
  3) Fallback estruturado sem LLM (base factual)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.prompts import (
    build_enrichment_prompt,
    build_system_prompt,
    build_user_prompt,
)
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
            temperature=0.25,
            api_key=s.openai_api_key,
        )
    return _llm_sintese


def _snapshot_json(snapshot: dict[str, Any], *, limite: int = 90000) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    if len(snapshot_json) > limite:
        snapshot_json = snapshot_json[:limite] + "\n…(truncado)"
    return snapshot_json


def _fallback_sem_llm(snapshot: dict[str, Any]) -> str:
    from app.services.report_md import montar_relatorio

    return montar_relatorio(snapshot)


def _ancoras_numericas(snapshot: dict[str, Any]) -> list[str]:
    """Números que o texto enriquecido deve preservar."""
    try:
        from app.services.report_content import metricas_base

        m = metricas_base(snapshot)
        vals = [
            m["n_atr"],
            m["n_hoje"],
            m["n_working"],
            m["n_ruins"],
            m["n_el"],
            m["n_total_w"],
        ]
        return [str(v) for v in vals if v not in (None, 0, "0")]
    except Exception:
        return []


def _parece_relatorio_valido(texto: str, snapshot: dict[str, Any]) -> bool:
    if not texto or len(texto.strip()) < 700:
        logger.warning("síntese rejeitada: texto curto (%s chars)", len(texto or ""))
        return False
    if texto.count("##") < 3:
        logger.warning("síntese rejeitada: poucas seções Markdown")
        return False
    low = texto.lower()
    if any(p in low[:120] for p in ("claro,", "aqui está", "com certeza", "segue o relatório gerado")):
        # prefácio conversacional — ainda pode ser usável se o resto for bom
        pass
    ancoras = _ancoras_numericas(snapshot)
    if ancoras:
        hits = sum(1 for a in ancoras if a in texto)
        if hits < min(2, len(ancoras)):
            logger.warning(
                "síntese rejeitada: âncoras numéricas fracas (hits=%s/%s)",
                hits,
                len(ancoras),
            )
            return False
    return True


def _limpar_prefácio(texto: str) -> str:
    linhas = texto.strip().splitlines()
    while linhas and not linhas[0].strip().startswith("#"):
        # descarta intro conversacional antes do título
        if linhas[0].strip():
            # se a primeira linha já é conteúdo útil sem #, para
            if len(linhas[0]) > 80:
                break
        linhas.pop(0)
    return "\n".join(linhas).strip()


async def sintetizar_relatorio(snapshot: dict[str, Any], *, conversation_id: str = "") -> str:
    """Síntese via Infinity Lab (prioridade) → OpenAI → base factual.

    A base factual (`montar_relatorio`) ancora os números. A Lab enriquece
    em relatório consolidado — o PDF deve usar esse Markdown, não o template cru.
    """
    s = get_settings()
    base = _fallback_sem_llm(snapshot)
    # Lab: JSON menor (base MD já tem os números). OpenAI aguenta mais.
    snap_json_lab = _snapshot_json(snapshot, limite=45000)
    snap_json_full = _snapshot_json(snapshot, limite=90000)
    user_lab = build_enrichment_prompt(base_md=base, snapshot_json=snap_json_lab)
    conv = conversation_id or f"relatorio-{(snapshot.get('rotulo') or 'diario')}"

    if s.infinity_lab_enabled:
        try:
            logger.info("síntese via Infinity Lab (agente=%s)", s.infinity_lab_agent_id)
            texto = await infinity_lab.chat(
                content=user_lab,
                conversation_id=conv,
                purpose="relatorio",
                timeout=200.0,
                retries=2,
            )
            texto = _limpar_prefácio(texto or "")
            if _parece_relatorio_valido(texto, snapshot):
                logger.info("Infinity Lab OK — relatório enriquecido (%s chars)", len(texto))
                return texto
            logger.warning("Infinity Lab respondeu mas validação falhou — tentando OpenAI/fallback")
        except Exception:
            logger.exception("Infinity Lab falhou na síntese — tentando fallback")

    if s.openai_api_key:
        try:
            logger.info("síntese via OpenAI (fallback)")
            user_oa = build_enrichment_prompt(base_md=base, snapshot_json=snap_json_full)
            msgs = [
                SystemMessage(content=build_system_prompt()),
                HumanMessage(content=user_oa),
            ]
            resp = await _llm().ainvoke(msgs)
            texto = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
            texto = _limpar_prefácio(texto)
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
                prompt=user_oa[:8000],
                completion=texto,
                usage=usage if isinstance(usage, dict) else {},
                ok=bool(texto),
            )
            if _parece_relatorio_valido(texto, snapshot):
                return texto
        except Exception:
            logger.exception("OpenAI falhou na síntese — usando base factual")
            try:
                from app.services import metrics as metrics_svc

                metrics_svc.record_llm_from_texts(
                    provider="openai",
                    purpose="relatorio",
                    prompt=user_oa[:8000],
                    completion="",
                    ok=False,
                )
            except Exception:
                pass

    logger.warning("usando base factual determinística (sem enriquecimento LLM)")
    return base


async def perguntar(thread_id: str, pergunta: str) -> str:
    """Pergunta sobre o último relatório."""
    s = get_settings()

    if s.infinity_lab_enabled:
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
