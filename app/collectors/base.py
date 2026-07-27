"""Contrato comum dos collectors.

Cada fonte devolve um dict tipado com:
  status: ok | stub | erro
  fonte: nome legível
  coletado_em: ISO-8601
  dados: payload (ou avisos, se stub/erro)
"""

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict


FonteStatus = Literal["ok", "stub", "erro"]


class ColetaResult(TypedDict):
    status: FonteStatus
    fonte: str
    coletado_em: str
    dados: dict[str, Any]


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resultado_ok(fonte: str, dados: dict[str, Any]) -> ColetaResult:
    return {"status": "ok", "fonte": fonte, "coletado_em": agora_iso(), "dados": dados}


def resultado_stub(fonte: str, motivo: str) -> ColetaResult:
    return {
        "status": "stub",
        "fonte": fonte,
        "coletado_em": agora_iso(),
        "dados": {"aviso": motivo, "pendente": True},
    }


def resultado_erro(fonte: str, erro: str) -> ColetaResult:
    return {
        "status": "erro",
        "fonte": fonte,
        "coletado_em": agora_iso(),
        "dados": {"erro": erro},
    }
