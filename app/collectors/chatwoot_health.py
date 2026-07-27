"""Collector Chatwoot — silêncio da IA + candidatos a reprocessamento.

Regra de negócio (determinística):
  1. Conversas abertas (opcionalmente filtradas por inbox)
  2. Última mensagem do lead (incoming, não privada) há >= N minutos
  3. Sem resposta outgoing depois dela
  4. Sem etiqueta de pausa (ex.: pausar_ia) → elegível
  5. Com etiqueta de pausa → só reporta como "pausado, não reprocessar"

Causa raiz do erro: o Chatwoot sozinho quase nunca traz "por que a IA falhou".
Só preenchemos causa_suspeita se houver label/nota/atributo explícito.
Caso contrário: silencio_sem_causa_explicita.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import ColetaResult, resultado_erro, resultado_ok, resultado_stub
from app.config import get_settings

logger = logging.getLogger("monitor.chatwoot")

FONTE = "chatwoot-ias"

# Labels que indicam "humano/kill-switch — não mexer".
PAUSE_LABEL_ALIASES_DEFAULT = ("pausar_ia", "pausar-ia", "pause_ia", "ia_pausada")


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


def montar_payload_reprocess(
    conv: dict[str, Any],
    *,
    minutos_sem_resposta: float,
    ultimo_incoming_em: str,
    pausado: bool,
    causa_suspeita: str | None,
    telefone: str,
    nome: str,
) -> dict[str, Any]:
    """Contrato estável pra o sistema do Francisco (ajustável quando o map chegar)."""
    cid = conv.get("id")
    meta = conv.get("meta") or {}
    sender = meta.get("sender") or {}
    return {
        "motivo": "silencio_ia",
        "regra": "lead_sem_resposta_ia_gt_threshold",
        "conversation_id": cid,
        "inbox_id": conv.get("inbox_id") or (conv.get("inbox") or {}).get("id"),
        "contact_id": sender.get("id") or conv.get("contact_id"),
        "telefone": telefone,
        "nome": nome,
        "labels": _labels_de(conv),
        "pausado": pausado,
        "ultimo_incoming_em": ultimo_incoming_em,
        "minutos_sem_resposta": round(minutos_sem_resposta, 1),
        "causa_suspeita": causa_suspeita,
        "causa_conhecida": causa_suspeita is not None,
        "status_conversa": conv.get("status"),
        "fonte": "chatwoot",
    }


def analisar_conversa(
    conv: dict[str, Any],
    mensagens_payload: Any,
    *,
    silencio_minutos: float,
    pause_labels: set[str],
    agora: datetime | None = None,
) -> dict[str, Any] | None:
    """Devolve candidato (pausado ou elegível) ou None se conversa ok / sem incoming."""
    agora = agora or _agora()
    mensagens = [m for m in _as_msg_list(mensagens_payload) if _mensagem_relevante(m)]
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
    pausado = _tem_pausa(labels, pause_labels)
    meta = conv.get("meta") or {}
    sender = meta.get("sender") or {}
    telefone = str(
        sender.get("phone_number")
        or sender.get("identifier")
        or conv.get("meta", {}).get("sender", {}).get("phone_number")
        or ""
    ).lstrip("+")
    nome = str(sender.get("name") or sender.get("available_name") or "")

    causa = _causa_suspeita(conv, _as_msg_list(mensagens_payload))
    payload = montar_payload_reprocess(
        conv,
        minutos_sem_resposta=minutos,
        ultimo_incoming_em=ts.isoformat(),
        pausado=pausado,
        causa_suspeita=causa,
        telefone=telefone,
        nome=nome,
    )
    payload["elegivel_reprocessamento"] = not pausado
    return payload


async def _varrer_candidatos(client: ChatwootHealthClient) -> dict[str, Any]:
    s = get_settings()
    silencio = float(s.chatwoot_silence_minutes)
    pause_labels = set(s.pause_labels)
    inbox = s.chatwoot_inbox_id or None
    max_pages = max(1, int(s.chatwoot_max_pages))
    max_convs = max(1, int(s.chatwoot_max_conversations))

    elegiveis: list[dict[str, Any]] = []
    pausados: list[dict[str, Any]] = []
    analisadas = 0
    erros_msg = 0

    for page in range(1, max_pages + 1):
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
            analisadas += 1
            try:
                msgs = await client.mensagens(cid)
                item = analisar_conversa(
                    conv,
                    msgs,
                    silencio_minutos=silencio,
                    pause_labels=pause_labels,
                )
            except Exception:
                erros_msg += 1
                logger.warning("falha ao ler mensagens da conversa %s", cid, exc_info=True)
                continue

            if not item:
                continue
            if item.get("pausado"):
                pausados.append(item)
            else:
                elegiveis.append(item)

        if analisadas >= max_convs or len(convs) < 10:
            # página curta: provavelmente acabou
            if len(convs) < 5:
                break

    elegiveis.sort(key=lambda x: float(x.get("minutos_sem_resposta") or 0), reverse=True)
    return {
        "silencio_minutos": silencio,
        "pause_labels": sorted(pause_labels),
        "conversas_analisadas": analisadas,
        "erros_ao_ler_mensagens": erros_msg,
        "leads_elegiveis_reprocessamento": elegiveis,
        "leads_pausados_ignorados": pausados,
        "totais": {
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

    if not (s.chatwoot_base_url and s.chatwoot_api_token and s.chatwoot_account_id):
        return resultado_erro(
            FONTE,
            "CHATWOOT_HEALTH_ENABLED=true mas faltam BASE_URL / ACCOUNT_ID / API_TOKEN",
        )

    client = ChatwootHealthClient(
        s.chatwoot_base_url,
        s.chatwoot_account_id,
        s.chatwoot_api_token,
    )
    try:
        dados = await _varrer_candidatos(client)
        return resultado_ok(FONTE, dados)
    except Exception as e:
        logger.exception("chatwoot health falhou")
        return resultado_erro(FONTE, str(e))
