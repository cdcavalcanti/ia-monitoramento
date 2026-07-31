"""Cache em memória (+ disco leve) do último snapshot operacional.

A UI lê daqui para não esperar 10+ min de varredura Chatwoot a cada refresh.
Pollers escrevem após cada coleta bem-sucedida.

Cada item inclui `log` — motivo legível do porquê está na lista.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("monitor.ops_cache")

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "chatwoot": None,
    "waha": None,
    "painel": None,
}

WAHA_STATUS_LOG = {
    "FAILED": "Sessão caiu (FAILED). WhatsApp desconectou ou o worker quebrou — reconectar/escanear QR.",
    "STOPPED": "Sessão parada (STOPPED). Foi interrompida manualmente ou pelo sistema.",
    "SCAN_QR_CODE": "Aguardando QR Code. Precisa escanear de novo no celular.",
    "STARTING": "Sessão ainda iniciando. Se ficar assim, reinicie a instância.",
    "BROKEN": "Sessão quebrada (BROKEN). Reinicie ou recrie a sessão no WAHA.",
    "UNKNOWN": "Status desconhecido na API WAHA.",
}


def _path() -> Path:
    s = get_settings()
    s.ensure_dirs()
    return s.data_dir / "ops_cache.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist() -> None:
    try:
        _path().write_text(json.dumps(_cache, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def load_disk() -> None:
    p = _path()
    if not p.is_file():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        # Import tardio evita ciclo no boot.
        from app.collectors.chatwoot_health import snapshot_eh_de_hoje

        s = get_settings()
        with _lock:
            for k in ("chatwoot", "waha", "painel"):
                if data.get(k) is not None:
                    _cache[k] = data[k]
            cw = _cache.get("chatwoot")
            if isinstance(cw, dict) and cw.get("atualizado_em"):
                if not snapshot_eh_de_hoje(cw.get("atualizado_em"), tz_name=s.report_timezone):
                    logger.warning(
                        "ops_cache chatwoot descartado (não é de hoje): %s",
                        cw.get("atualizado_em"),
                    )
                    _cache["chatwoot"] = None
                    try:
                        _persist()
                    except Exception:
                        pass
    except Exception:
        pass


def _sanear_chatwoot_view(cw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Garante que elegíveis expostos à UI/relatório sejam só do dia corrente."""
    if not cw or not isinstance(cw, dict):
        return cw
    if not bool(cw.get("somente_hoje", True)):
        return cw
    from app.collectors.chatwoot_health import filtrar_leads_somente_hoje, snapshot_eh_de_hoje

    s = get_settings()
    if cw.get("atualizado_em") and not snapshot_eh_de_hoje(
        cw.get("atualizado_em"), tz_name=s.report_timezone
    ):
        return None
    elegiveis = list(cw.get("elegiveis") or [])
    filtrados = filtrar_leads_somente_hoje(elegiveis, tz_name=s.report_timezone)
    if len(filtrados) == len(elegiveis):
        return cw
    out = dict(cw)
    out["elegiveis"] = filtrados
    totais = dict(out.get("totais") or {})
    totais["elegiveis"] = len(filtrados)
    out["totais"] = totais
    return out


def _log_chatwoot_elegivel(x: dict[str, Any], *, silencio: float, somente_hoje: bool) -> str:
    mins = x.get("minutos_sem_resposta")
    partes = [
        f"Lead enviou mensagem e a IA não respondeu há {mins} min"
        + (f" (limite {silencio:g} min)" if silencio else "")
        + "."
    ]
    if somente_hoje:
        partes.append("Regra: só contamos silêncio de hoje.")
    if x.get("causa_suspeita"):
        partes.append(f"Pista no Chatwoot: {x.get('causa_suspeita')}.")
    else:
        partes.append("Sem causa explícita no Chatwoot (label/nota/atributo de erro).")
    partes.append("Elegível a reprocessar (sem pausar_ia).")
    return " ".join(partes)


def _log_chatwoot_pausado(x: dict[str, Any]) -> str:
    labels = x.get("labels") or []
    lab = ", ".join(str(l) for l in labels[:6]) if labels else "pausa/skip"
    motivo = x.get("motivo_bloqueio")
    if motivo:
        return (
            f"Conversa bloqueada para reprocessamento ({motivo}). "
            f"Silêncio há {x.get('minutos_sem_resposta')} min — não elegível."
        )
    return (
        f"Conversa com etiqueta de pausa/handoff ({lab}). "
        "Atendimento humano ou agendamento — a IA de monitoramento NÃO deve reprocessar. "
        f"Silêncio há {x.get('minutos_sem_resposta')} min."
    )


def _log_waha(x: dict[str, Any]) -> str:
    st = str(x.get("status") or "UNKNOWN").upper()
    base = WAHA_STATUS_LOG.get(st, f"Status `{st}` — sessão fora de WORKING.")
    raw = x.get("raw") if isinstance(x.get("raw"), dict) else {}
    extras: list[str] = []
    me = raw.get("me")
    if isinstance(me, dict) and me.get("id"):
        extras.append(f"número vinculado: {me.get('id')}")
    elif isinstance(me, str) and me:
        extras.append(f"me: {me}")
    eng = raw.get("engine")
    if eng:
        extras.append(f"engine: {eng}")
    if extras:
        return f"{base} ({'; '.join(extras)})"
    return base


def _log_hub_servico(item: dict[str, Any]) -> str:
    nome = item.get("nome") or "?"
    status = item.get("status") or "desconhecido"
    nivel = item.get("nivel") or "ruim"
    tipo = item.get("tipo") or "serviço"
    return (
        f"{tipo} `{nome}` está em estado `{status}` (nível {nivel}). "
        "Hub marcou como problema — verificar no Painel de Status."
    )


def _log_hub_alerta(texto: str) -> str:
    return f"Alerta do Hub: {texto}"


def _log_conta(c: dict[str, Any]) -> str:
    if c.get("skipped") or c.get("erro") == "sem_inbox_ia_configurada":
        return "Conta sem inbox de IA configurada — varredura pulada até cadastrar a caixa."
    if c.get("erro"):
        return f"Falha ao varrer esta conta: {c.get('erro')}"
    n = int(c.get("elegiveis") or 0)
    if n > 0:
        return f"{n} lead(s) elegível(is) nesta conta na última varredura."
    return (
        f"Sem elegíveis. Analisadas {c.get('conversas_analisadas') or 0} conversas "
        f"nas inboxes {(c.get('inbox_ids') or [])}."
    )


def set_chatwoot(dados: dict[str, Any], *, status: str = "ok") -> None:
    elegiveis = list(dados.get("leads_elegiveis_reprocessamento") or [])
    pausados = list(dados.get("leads_pausados_ignorados") or [])
    silencio = float(dados.get("silencio_minutos") or 5)
    somente_hoje = bool(dados.get("somente_hoje", True))

    slim_e = []
    for x in elegiveis[:80]:
        slim_e.append(
            {
                "cliente": x.get("account_nome"),
                "account_id": x.get("account_id"),
                "conversation_id": x.get("conversation_id"),
                "inbox_id": x.get("inbox_id"),
                "nome": x.get("nome"),
                "telefone": x.get("telefone"),
                "minutos_sem_resposta": x.get("minutos_sem_resposta"),
                "link": x.get("link"),
                "pausado": False,
                "causa_suspeita": x.get("causa_suspeita"),
                "ultimo_incoming_em": x.get("ultimo_incoming_em"),
                "labels": x.get("labels") or [],
                "log": _log_chatwoot_elegivel(x, silencio=silencio, somente_hoje=somente_hoje),
            }
        )
    slim_p = []
    for x in pausados[:40]:
        slim_p.append(
            {
                "cliente": x.get("account_nome"),
                "account_id": x.get("account_id"),
                "conversation_id": x.get("conversation_id"),
                "inbox_id": x.get("inbox_id"),
                "nome": x.get("nome"),
                "minutos_sem_resposta": x.get("minutos_sem_resposta"),
                "link": x.get("link"),
                "pausado": True,
                "labels": x.get("labels") or [],
                "motivo_bloqueio": x.get("motivo_bloqueio"),
                "ultimo_incoming_em": x.get("ultimo_incoming_em"),
                "log": _log_chatwoot_pausado(x),
            }
        )
    por_conta = []
    for c in dados.get("contas") or []:
        item = {
            "account_id": c.get("account_id"),
            "account_nome": c.get("account_nome"),
            "inbox_ids": c.get("inbox_ids") or [],
            "elegiveis": c.get("elegiveis"),
            "pausados_com_silencio": c.get("pausados_com_silencio"),
            "conversas_analisadas": c.get("conversas_analisadas"),
            "skipped": c.get("skipped"),
            "erro": c.get("erro"),
        }
        item["log"] = _log_conta(item)
        por_conta.append(item)

    payload = {
        "atualizado_em": _now(),
        "status": status,
        "somente_hoje": somente_hoje,
        "silencio_minutos": silencio,
        "totais": dados.get("totais") or {},
        "conversas_analisadas": dados.get("conversas_analisadas"),
        "por_conta": por_conta,
        "elegiveis": slim_e,
        "pausados": slim_p,
    }
    with _lock:
        _cache["chatwoot"] = payload
        _persist()


def set_waha(dados: dict[str, Any], *, status: str = "ok") -> None:
    ruins = []
    for x in dados.get("ruins") or []:
        if not isinstance(x, dict):
            continue
        ruins.append(
            {
                "name": x.get("name"),
                "status": x.get("status"),
                "raw": x.get("raw") or {},
                "log": _log_waha(x),
            }
        )
    working = [
        {"name": x.get("name"), "status": x.get("status")}
        for x in (dados.get("sessoes") or [])
        if isinstance(x, dict) and x.get("ok")
    ]
    payload = {
        "atualizado_em": _now(),
        "status": status,
        "totais": dados.get("totais") or {},
        "ruins": ruins,
        "working_sample": working[:12],
        "log_geral": (
            None
            if status == "ok"
            else "Falha ao consultar a API WAHA — verifique URL/token/X-Api-Key."
        ),
    }
    with _lock:
        _cache["waha"] = payload
        _persist()


def set_painel(dados: dict[str, Any], *, status: str = "ok") -> None:
    norm = dados.get("normalizado") if isinstance(dados.get("normalizado"), dict) else {}
    alertas_raw = list(dados.get("alertas_api") or [])[:20]
    if not alertas_raw:
        alertas_raw = list(norm.get("alertas_api") or [])[:20]

    alertas = []
    for a in alertas_raw:
        texto = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
        alertas.append({"texto": texto, "log": _log_hub_alerta(texto)})

    servicos = []
    for item in dados.get("servicos") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("nivel") or "") == "ok":
            continue
        row = {
            "nome": item.get("nome"),
            "tipo": item.get("tipo"),
            "status": item.get("status"),
            "nivel": item.get("nivel"),
        }
        row["log"] = _log_hub_servico(row)
        servicos.append(row)
    if not servicos:
        for item in norm.get("itens_alerta") or []:
            if not isinstance(item, dict):
                continue
            row = {
                "nome": item.get("nome") or item.get("id") or item.get("label"),
                "tipo": item.get("tipo") or "alerta",
                "status": item.get("status") or item.get("estado") or "problema",
                "nivel": item.get("nivel") or "ruim",
            }
            row["log"] = _log_hub_servico(row)
            servicos.append(row)

    clientes = list(dados.get("clientes_com_problema") or [])[:30]
    if not clientes:
        clientes = list(norm.get("clientes_problema") or [])[:30]
    if not clientes and isinstance(norm.get("clientes_resumo"), (list, dict, str)):
        cr = norm.get("clientes_resumo")
        if isinstance(cr, list):
            clientes = cr[:30]
        elif isinstance(cr, str) and cr.strip():
            clientes = [cr]

    clientes_out = []
    for c in clientes:
        if isinstance(c, str):
            clientes_out.append(
                {
                    "nome": c,
                    "log": f"Cliente em estado parcial/offline no Hub: {c}.",
                }
            )
        elif isinstance(c, dict):
            nome = c.get("nome") or c.get("cliente") or json.dumps(c, ensure_ascii=False)
            clientes_out.append(
                {
                    "nome": nome,
                    "status": c.get("status") or c.get("estado"),
                    "log": (
                        f"Cliente `{nome}` com problema no Hub"
                        + (f" (status {c.get('status') or c.get('estado')})" if (c.get("status") or c.get("estado")) else "")
                        + "."
                    ),
                }
            )

    saude = (
        (dados.get("totais") or {}).get("saudeGeral")
        or norm.get("saudeGeral")
        or (dados.get("overview") or {}).get("saudeGeral")
    )
    payload = {
        "atualizado_em": _now(),
        "status": status,
        "totais": dados.get("totais") or {},
        "saudeGeral": saude,
        "alertas": alertas,
        "servicos_problema": servicos[:40],
        "clientes_problema": clientes_out,
        "log_geral": (
            f"Saúde geral do Hub: {saude}."
            if saude
            else ("Falha ao consultar Hub." if status != "ok" else None)
        ),
    }
    with _lock:
        _cache["painel"] = payload
        _persist()


def get_all() -> dict[str, Any]:
    with _lock:
        cw = _cache.get("chatwoot")
        return {
            "chatwoot": _sanear_chatwoot_view(cw if isinstance(cw, dict) else None),
            "waha": _cache.get("waha"),
            "painel": _cache.get("painel"),
        }
