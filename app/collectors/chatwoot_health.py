"""Collector Chatwoot — silêncio da IA + candidatos a reprocessamento.

Regra de negócio (determinística):
  1. Conversas abertas nas inboxes das IAs (por conta cliente)
  2. Última mensagem do lead (incoming, não privada) há >= N minutos
  3. Sem resposta outgoing depois dela
  4. Último incoming é do dia corrente (America/Sao_Paulo) — não reprocessa legado
  5. Sem etiqueta de pausa/skip (ex.: pausar_ia, lead_agendado) → elegível
  6. Com pausa, skip (agendado/transferido) ou activity de handoff → não reprocessar
  7. Relatório/cache só usa snapshot do dia corrente

Causa raiz do erro: o Chatwoot sozinho quase nunca traz "por que a IA falhou".
Só preenchemos causa_suspeita se houver label/nota/atributo explícito.
Caso contrário: silencio_sem_causa_explicita.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok, resultado_stub
from app.config import get_settings

logger = logging.getLogger("monitor.chatwoot")

FONTE = "chatwoot-ias"

# Labels que indicam "humano/kill-switch — não mexer".
PAUSE_LABEL_ALIASES_DEFAULT = ("pausar_ia", "pausar-ia", "pause_ia", "ia_pausada")


def _tz_negocio(nome: str | None = None):
    s = get_settings()
    raw = (nome or s.report_timezone or "America/Sao_Paulo").strip()
    try:
        return ZoneInfo(raw)
    except Exception:
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            # Windows sem tzdata: UTC-3 fixo (Brasil sem DST desde 2019).
            from datetime import timedelta

            return timezone(timedelta(hours=-3))


def _eh_hoje(ts: datetime, *, agora: datetime, tz_name: str | None = None) -> bool:
    """True se o timestamp cai no mesmo dia civil de `agora` no fuso do negócio."""
    tz = _tz_negocio(tz_name)
    local_ts = ts.astimezone(tz)
    local_agora = agora.astimezone(tz)
    return local_ts.date() == local_agora.date()


def snapshot_eh_de_hoje(atualizado_em: Any, *, tz_name: str | None = None, agora: datetime | None = None) -> bool:
    """True se o snapshot (ISO/`atualizado_em`) foi gerado no dia civil corrente."""
    ts = _parse_ts(atualizado_em)
    if not ts:
        return False
    return _eh_hoje(ts, agora=agora or _agora(), tz_name=tz_name)


def filtrar_leads_somente_hoje(
    leads: list[dict[str, Any]],
    *,
    tz_name: str | None = None,
    agora: datetime | None = None,
) -> list[dict[str, Any]]:
    """Mantém só leads cujo ultimo_incoming_em é do dia corrente."""
    agora = agora or _agora()
    out: list[dict[str, Any]] = []
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        ts = _parse_ts(lead.get("ultimo_incoming_em"))
        if not ts:
            continue
        if _eh_hoje(ts, agora=agora, tz_name=tz_name):
            out.append(lead)
    return out


# Palavras em activity/labels que indicam handoff humano ou agendamento.
_HANDOFF_MARKERS = (
    "lead_agendado",
    "transfer",
    "transferid",
    "atribu",
    "assigned",
    "assumed control",
    "atendimento_humano",
    "handoff",
    "consulta_agendada",
)


class ChatwootHealthClient:
    def __init__(
        self,
        base_url: str,
        account_id: str,
        token: str,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_id = str(account_id)
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "api_access_token": self.token,
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def account(self) -> Any:
        return await self._get(f"/api/v1/accounts/{self.account_id}")

    async def listar_conversas(
        self,
        *,
        status: str = "open",
        page: int = 1,
        inbox_id: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"status": status, "page": page}
        if inbox_id:
            params["inbox_id"] = inbox_id
        return await self._get(
            f"/api/v1/accounts/{self.account_id}/conversations",
            params,
        )

    async def mensagens(self, conversation_id: int | str) -> Any:
        return await self._get(
            f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"
        )


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Chatwoot costuma mandar unix seconds
        ts = float(value)
        if ts > 1e12:  # ms
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _labels_de(conv: dict[str, Any]) -> list[str]:
    raw = conv.get("labels") or conv.get("label_list") or []
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                out.append(str(item.get("title") or item.get("name") or item.get("slug") or ""))
    return [x.strip() for x in out if x and str(x).strip()]


def _tem_pausa(labels: list[str], pause_labels: set[str]) -> bool:
    normalizados = {l.lower().replace(" ", "_").replace("-", "_") for l in labels}
    alvos = {p.lower().replace(" ", "_").replace("-", "_") for p in pause_labels}
    return bool(normalizados & alvos)


def _normalizar_label(lab: str) -> str:
    return lab.lower().replace(" ", "_").replace("-", "_")


def _tem_skip(labels: list[str], skip_labels: set[str]) -> bool:
    if not skip_labels:
        return False
    normalizados = {_normalizar_label(l) for l in labels}
    alvos = {_normalizar_label(p) for p in skip_labels}
    return bool(normalizados & alvos)


def _eh_activity(m: dict[str, Any]) -> bool:
    mt = m.get("message_type")
    if mt in (2, "2", "activity", "Activity"):
        return True
    return str(m.get("content_type") or "").lower() == "activity"


def _teve_handoff(mensagens: list[dict[str, Any]], labels: list[str] | None = None) -> str | None:
    """Retorna motivo curto se houver evidência de transferência/agendamento."""
    for lab in labels or []:
        low = _normalizar_label(lab)
        for marker in _HANDOFF_MARKERS:
            if marker in low:
                return f"label:{lab}"

    for m in mensagens:
        if not _eh_activity(m) and not m.get("private"):
            # activity e notas privadas; conteúdo público normal não conta
            continue
        content = str(m.get("content") or "").lower()
        if not content:
            continue
        for marker in _HANDOFF_MARKERS:
            if marker in content:
                return f"activity:{content[:120]}"
    return None


def _as_msg_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    if isinstance(payload, dict):
        for key in ("payload", "messages", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return [m for m in v if isinstance(m, dict)]
            if isinstance(v, dict) and isinstance(v.get("messages"), list):
                return [m for m in v["messages"] if isinstance(m, dict)]
    return []


def _as_conv_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("payload"), list):
            return [c for c in data["payload"] if isinstance(c, dict)]
        for key in ("payload", "conversations", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return [c for c in v if isinstance(c, dict)]
    return []


def _mensagem_relevante(m: dict[str, Any]) -> bool:
    if m.get("private"):
        return False
    # activity/template não contam como fala lead↔IA
    mt = str(m.get("message_type") or m.get("content_type") or "")
    if mt in ("activity", "template", "2", "3"):
        # no Chatwoot: 0 incoming, 1 outgoing, 2 activity, 3 template (varia por versão)
        if mt in ("2", "3", "activity", "template"):
            return False
    # message_type pode ser int
    if m.get("message_type") in (2, 3):
        return False
    return True


def _eh_incoming(m: dict[str, Any]) -> bool:
    mt = m.get("message_type")
    return mt in (0, "incoming", "Incoming")


def _eh_outgoing(m: dict[str, Any]) -> bool:
    mt = m.get("message_type")
    return mt in (1, "outgoing", "Outgoing")


def _causa_suspeita(conv: dict[str, Any], mensagens: list[dict[str, Any]]) -> str | None:
    """Só retorna causa se houver evidência explícita — nunca inventa."""
    labels = _labels_de(conv)
    for lab in labels:
        low = lab.lower()
        if any(k in low for k in ("erro", "error", "fail", "falha", "timeout", "500")):
            return f"label:{lab}"

    attrs = conv.get("custom_attributes") or conv.get("additional_attributes") or {}
    if isinstance(attrs, dict):
        for k, v in attrs.items():
            blob = f"{k}={v}".lower()
            if any(x in blob for x in ("erro", "error", "fail", "timeout")):
                return f"atributo:{k}={v}"

    # últimas notas privadas
    for m in reversed(mensagens[-15:]):
        if not m.get("private"):
            continue
        content = str(m.get("content") or "").lower()
        if any(x in content for x in ("erro", "error", "exception", "timeout", "falha")):
            return f"nota_privada:{str(m.get('content') or '')[:180]}"

    return None


def link_conversa(
    base_url: str,
    account_id: str | int,
    inbox_id: str | int | None,
    conversation_id: str | int,
) -> str | None:
    """URL no formato /app/accounts/{conta}/inbox/{caixa}/conversations/{id}."""
    if inbox_id is None or conversation_id is None:
        return None
    base = str(base_url).rstrip("/")
    return (
        f"{base}/app/accounts/{account_id}/inbox/{inbox_id}/conversations/{conversation_id}"
    )


def montar_payload_reprocess(
    conv: dict[str, Any],
    *,
    minutos_sem_resposta: float,
    ultimo_incoming_em: str,
    pausado: bool,
    causa_suspeita: str | None,
    telefone: str,
    nome: str,
    account_id: str | None = None,
    account_nome: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Contrato estável pra o sistema do Francisco (ajustável quando o map chegar)."""
    cid = conv.get("id")
    meta = conv.get("meta") or {}
    sender = meta.get("sender") or {}
    inbox_id = conv.get("inbox_id") or (conv.get("inbox") or {}).get("id")
    contact_id = sender.get("id") or conv.get("contact_id")

    def _int(v: Any) -> int | None:
        try:
            if v is None or v == "":
                return None
            n = int(v)
            return n if n > 0 else None
        except Exception:
            return None

    aid_i = _int(account_id)
    cid_i = _int(cid)
    inbox_i = _int(inbox_id)
    contact_i = _int(contact_id)
    aid_s = str(aid_i) if aid_i is not None else (str(account_id) if account_id is not None else None)
    link = link_conversa(base_url or "", aid_s or "", inbox_id, cid) if aid_s and base_url else None
    return {
        "motivo": "silencio_ia",
        "regra": "lead_sem_resposta_ia_gt_threshold",
        "account_id": aid_i,
        "account_nome": account_nome,
        "conversation_id": cid_i,
        "inbox_id": inbox_i,
        "contact_id": contact_i,
        "telefone": telefone,
        "nome": nome,
        "labels": _labels_de(conv),
        "pausado": pausado,
        "ultimo_incoming_em": ultimo_incoming_em,
        "minutos_sem_resposta": round(minutos_sem_resposta, 1),
        "causa_suspeita": causa_suspeita,
        "causa_conhecida": causa_suspeita is not None,
        "status_conversa": conv.get("status"),
        "link": link,
        "fonte": "chatwoot",
    }


def analisar_conversa(
    conv: dict[str, Any],
    mensagens_payload: Any,
    *,
    silencio_minutos: float,
    pause_labels: set[str],
    agora: datetime | None = None,
    account_id: str | None = None,
    account_nome: str | None = None,
    base_url: str | None = None,
    only_today: bool = True,
    timezone_name: str | None = None,
    skip_labels: set[str] | None = None,
) -> dict[str, Any] | None:
    """Devolve candidato (pausado/bloqueado ou elegível) ou None se conversa ok / sem incoming.

    Com only_today=True (default), ignora silêncios cujo último incoming
    não é do dia corrente no fuso do negócio (REPORT_TIMEZONE).
    """
    agora = agora or _agora()
    todas = _as_msg_list(mensagens_payload)
    mensagens = [m for m in todas if _mensagem_relevante(m)]
    mensagens.sort(key=lambda m: _parse_ts(m.get("created_at") or m.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

    ultimo_incoming = None
    for m in reversed(mensagens):
        if _eh_incoming(m):
            ultimo_incoming = m
            break
    if not ultimo_incoming:
        return None

    ts = _parse_ts(ultimo_incoming.get("created_at") or ultimo_incoming.get("timestamp"))
    if not ts:
        return None

    if only_today and not _eh_hoje(ts, agora=agora, tz_name=timezone_name):
        return None

    # houve outgoing depois do último incoming?
    for m in mensagens:
        tsm = _parse_ts(m.get("created_at") or m.get("timestamp"))
        if not tsm or tsm <= ts:
            continue
        if _eh_outgoing(m):
            return None  # IA ou humano já respondeu

    minutos = (agora - ts).total_seconds() / 60.0
    if minutos < silencio_minutos:
        return None

    labels = _labels_de(conv)
    skip = set(skip_labels or ())
    pausado = _tem_pausa(labels, pause_labels)
    handoff = _teve_handoff(todas, labels)
    bloqueado = pausado or _tem_skip(labels, skip) or bool(handoff)
    meta = conv.get("meta") or {}
    sender = meta.get("sender") or {}
    telefone = str(
        sender.get("phone_number")
        or sender.get("identifier")
        or conv.get("meta", {}).get("sender", {}).get("phone_number")
        or ""
    ).lstrip("+")
    nome = str(sender.get("name") or sender.get("available_name") or "")

    causa = _causa_suspeita(conv, todas)
    payload = montar_payload_reprocess(
        conv,
        minutos_sem_resposta=minutos,
        ultimo_incoming_em=ts.isoformat(),
        pausado=bloqueado,
        causa_suspeita=causa,
        telefone=telefone,
        nome=nome,
        account_id=account_id,
        account_nome=account_nome,
        base_url=base_url,
    )
    payload["regra"] = "lead_sem_resposta_ia_gt_threshold_hoje" if only_today else payload["regra"]
    payload["somente_hoje"] = bool(only_today)
    payload["elegivel_reprocessamento"] = not bloqueado
    if handoff and not pausado:
        payload["motivo_bloqueio"] = handoff
    elif _tem_skip(labels, skip) and not pausado:
        payload["motivo_bloqueio"] = "skip_label"
    return payload


async def _varrer_conta(
    client: ChatwootHealthClient,
    *,
    account_nome: str,
    silencio: float,
    pause_labels: set[str],
    skip_labels: set[str],
    inbox_ids: list[str],
    max_pages: int,
    max_convs: int,
    base_url: str,
    only_today: bool,
    timezone_name: str,
) -> dict[str, Any]:
    elegiveis: list[dict[str, Any]] = []
    pausados: list[dict[str, Any]] = []
    analisadas = 0
    erros_msg = 0
    erro_conta: str | None = None

    if not inbox_ids:
        return {
            "account_id": client.account_id,
            "account_nome": account_nome,
            "inbox_ids": [],
            "conversas_analisadas": 0,
            "erros_ao_ler_mensagens": 0,
            "erro": "sem_inbox_ia_configurada",
            "skipped": True,
            "elegiveis": [],
            "pausados": [],
        }

    try:
        for inbox in inbox_ids:
            if analisadas >= max_convs:
                break
            for page in range(1, max_pages + 1):
                if analisadas >= max_convs:
                    break
                raw = await client.listar_conversas(status="open", page=page, inbox_id=inbox)
                convs = _as_conv_list(raw)
                if not convs:
                    break

                for conv in convs:
                    if analisadas >= max_convs:
                        break
                    cid = conv.get("id")
                    if cid is None:
                        continue
                    if not conv.get("inbox_id"):
                        conv = {**conv, "inbox_id": int(inbox) if str(inbox).isdigit() else inbox}
                    analisadas += 1
                    try:
                        msgs = await client.mensagens(cid)
                        item = analisar_conversa(
                            conv,
                            msgs,
                            silencio_minutos=silencio,
                            pause_labels=pause_labels,
                            skip_labels=skip_labels,
                            account_id=client.account_id,
                            account_nome=account_nome,
                            base_url=base_url,
                            only_today=only_today,
                            timezone_name=timezone_name,
                        )
                    except Exception:
                        erros_msg += 1
                        logger.warning(
                            "falha ao ler mensagens conta=%s inbox=%s conversa=%s",
                            client.account_id,
                            inbox,
                            cid,
                            exc_info=True,
                        )
                        continue

                    if not item:
                        continue
                    if item.get("pausado") or not item.get("elegivel_reprocessamento"):
                        pausados.append(item)
                    else:
                        elegiveis.append(item)

                if len(convs) < 5:
                    break
    except Exception as e:
        erro_conta = str(e)
        logger.warning("falha ao varrer conta %s (%s): %s", account_nome, client.account_id, e)

    return {
        "account_id": client.account_id,
        "account_nome": account_nome,
        "inbox_ids": inbox_ids,
        "conversas_analisadas": analisadas,
        "erros_ao_ler_mensagens": erros_msg,
        "erro": erro_conta,
        "skipped": False,
        "elegiveis": elegiveis,
        "pausados": pausados,
    }


async def _varrer_candidatos() -> dict[str, Any]:
    s = get_settings()
    silencio = float(s.chatwoot_silence_minutes)
    pause_labels = set(s.pause_labels)
    skip_labels = set(s.skip_labels)
    max_pages = max(1, int(s.chatwoot_max_pages))
    max_convs = max(1, int(s.chatwoot_max_conversations))
    only_today = bool(s.chatwoot_only_today)
    timezone_name = s.report_timezone
    contas = s.chatwoot_account_list

    elegiveis: list[dict[str, Any]] = []
    pausados: list[dict[str, Any]] = []
    por_conta: list[dict[str, Any]] = []
    analisadas = 0
    erros_msg = 0
    contas_ativas = 0
    contas_skipped = 0

    for conta in contas:
        client = ChatwootHealthClient(s.chatwoot_base_url, conta["id"], s.chatwoot_api_token)
        inbox_ids = list(conta.get("inbox_ids") or [])
        res = await _varrer_conta(
            client,
            account_nome=conta["nome"],
            silencio=silencio,
            pause_labels=pause_labels,
            skip_labels=skip_labels,
            inbox_ids=inbox_ids,
            max_pages=max_pages,
            max_convs=max_convs,
            base_url=s.chatwoot_base_url,
            only_today=only_today,
            timezone_name=timezone_name,
        )
        if res.get("skipped"):
            contas_skipped += 1
        else:
            contas_ativas += 1
        elegiveis.extend(res["elegiveis"])
        pausados.extend(res["pausados"])
        analisadas += int(res["conversas_analisadas"])
        erros_msg += int(res["erros_ao_ler_mensagens"])
        por_conta.append(
            {
                "account_id": res["account_id"],
                "account_nome": res["account_nome"],
                "inbox_ids": res.get("inbox_ids") or [],
                "conversas_analisadas": res["conversas_analisadas"],
                "elegiveis": len(res["elegiveis"]),
                "pausados_com_silencio": len(res["pausados"]),
                "erros_ao_ler_mensagens": res["erros_ao_ler_mensagens"],
                "erro": res["erro"],
                "skipped": bool(res.get("skipped")),
            }
        )
        logger.info(
            "conta %s (%s) inboxes=%s: analisadas=%s elegiveis=%s pausados=%s erro=%s",
            conta["nome"],
            conta["id"],
            inbox_ids,
            res["conversas_analisadas"],
            len(res["elegiveis"]),
            len(res["pausados"]),
            res["erro"],
        )

    elegiveis.sort(key=lambda x: float(x.get("minutos_sem_resposta") or 0), reverse=True)
    return {
        "silencio_minutos": silencio,
        "somente_hoje": only_today,
        "timezone": timezone_name,
        "pause_labels": sorted(pause_labels),
        "skip_labels": sorted(skip_labels),
        "contas": por_conta,
        "conversas_analisadas": analisadas,
        "erros_ao_ler_mensagens": erros_msg,
        "leads_elegiveis_reprocessamento": elegiveis,
        "leads_pausados_ignorados": pausados,
        "totais": {
            "contas": len(contas),
            "contas_ativas": contas_ativas,
            "contas_sem_inbox": contas_skipped,
            "elegiveis": len(elegiveis),
            "pausados_com_silencio": len(pausados),
        },
        "limitacao_causa": (
            "Chatwoot sozinho não expõe o stack trace da IA. "
            "causa_suspeita só vem de label/nota/atributo explícito; "
            "senão fica null (silêncio sem causa conhecida)."
        ),
    }


async def coletar() -> ColetaResult:
    s = get_settings()
    if not s.chatwoot_health_enabled:
        return resultado_stub(
            FONTE,
            "Monitoramento Chatwoot/IAs ainda não ligado "
            "(CHATWOOT_HEALTH_ENABLED=false). Credenciais + token necessários.",
        )

    contas = s.chatwoot_account_list
    if not (s.chatwoot_base_url and s.chatwoot_api_token and contas):
        return resultado_erro(
            FONTE,
            "CHATWOOT_HEALTH_ENABLED=true mas faltam BASE_URL / API_TOKEN / "
            "CHATWOOT_ACCOUNTS (ou CHATWOOT_ACCOUNT_ID)",
        )

    try:
        dados = await _varrer_candidatos()
        return resultado_ok(FONTE, dados)
    except Exception as e:
        logger.exception("chatwoot health falhou")
        return resultado_erro(FONTE, str(e))
