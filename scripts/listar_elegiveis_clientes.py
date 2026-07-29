"""Varre contas cliente e grava elegíveis com links."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.collectors import chatwoot_health
from app.config import get_settings

OUT = Path("data/elegiveis_clientes.json")


def log(msg: str) -> None:
    print(msg, flush=True)


async def main() -> None:
    s = get_settings()
    contas = s.chatwoot_account_list
    log(f"contas={len(contas)} ids={[c['id'] for c in contas]}")
    log("varrendo (pode demorar: N contas x mensagens)...")
    r = await chatwoot_health.coletar()
    status = r["status"]
    dados = r.get("dados") or {}
    if status != "ok":
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"status={status} -> {OUT}")
        return

    elegiveis = dados.get("leads_elegiveis_reprocessamento") or []
    payload = {
        "total": len(elegiveis),
        "analisadas": dados.get("conversas_analisadas"),
        "por_conta": dados.get("contas"),
        "pausados_com_silencio": (dados.get("totais") or {}).get("pausados_com_silencio"),
        "leads": [
            {
                "cliente": x.get("account_nome"),
                "account_id": x.get("account_id"),
                "conversation_id": x.get("conversation_id"),
                "inbox_id": x.get("inbox_id"),
                "nome": x.get("nome"),
                "telefone": x.get("telefone"),
                "minutos_sem_resposta": x.get("minutos_sem_resposta"),
                "link": x.get("link"),
            }
            for x in elegiveis
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"TOTAL={len(elegiveis)} analisadas={payload['analisadas']} -> {OUT}")
    for c in payload["por_conta"] or []:
        log(
            f"  {c.get('account_nome')} ({c.get('account_id')}): "
            f"anal={c.get('conversas_analisadas')} eleg={c.get('elegiveis')} "
            f"paus={c.get('pausados_com_silencio')} err={c.get('erro')}"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
