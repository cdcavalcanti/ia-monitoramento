"""Smoke do cache Chatwoot → relatório — sem rede.

Regressão: o lead salvo no cache perdia `elegivel_reprocessamento`, e o
relatório (que lê o cache) dizia "nenhum elegível" com elegíveis detectados.

    python -m scripts.smoke_ops_cache
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Antes de importar app.*: dados em pasta temporária e reprocess DESLIGADO
# (enviar_lote vira stub, nada sai pela rede). Env var vence o .env.
_tmp = tempfile.mkdtemp(prefix="smoke_ops_cache_")
os.environ.update(
    DATA_DIR=_tmp,
    SQLITE_PATH=os.path.join(_tmp, "monitoramento.db"),
    REPROCESS_ENABLED="false",
)
sys.path.insert(0, ".")

from app.collectors.chatwoot_health import analisar_conversa  # noqa: E402
from app.services import metrics, ops_cache  # noqa: E402
from app.services.pipeline import _chatwoot_from_cache  # noqa: E402
from app.services.reprocess import enviar_lote  # noqa: E402


def _lead() -> dict:
    agora = datetime.now(timezone.utc)
    conv = {
        "id": 101,
        "inbox_id": 10,
        "status": "open",
        "labels": [],
        "meta": {"sender": {"id": 7, "name": "Lead Teste", "phone_number": "+5521999999999"}},
    }
    msgs = {"payload": [{"message_type": 0, "content": "oi", "created_at": (agora - timedelta(minutes=12)).timestamp()}]}
    item = analisar_conversa(
        conv, msgs, silencio_minutos=5, pause_labels={"pausar_ia"}, agora=agora, account_id="31", only_today=True
    )
    assert item and item["elegivel_reprocessamento"] is True, item
    return item


def _relatorio_ve_elegivel(etapa: str) -> None:
    cached = ops_cache.get_all()["chatwoot"]
    lead = cached["elegiveis"][0]
    assert lead.get("elegivel_reprocessamento") is True, f"{etapa}: cache perdeu o campo: {sorted(lead)}"
    cw = _chatwoot_from_cache(cached)
    r = asyncio.run(enviar_lote(cw["leads_elegiveis_reprocessamento"]))
    # Com o bug o lote chegava vazio ("nenhum elegível"); o certo é chegar ao envio (stub).
    assert r["status"] == "stub" and r["pulados"] == 1, f"{etapa}: {r}"


def main() -> None:
    metrics.init()
    lead = _lead()
    ops_cache.set_chatwoot(
        {"leads_elegiveis_reprocessamento": [lead], "silencio_minutos": 5, "somente_hoje": True, "totais": {}}
    )
    _relatorio_ve_elegivel("set_chatwoot")

    # Revalidação do dash regrava a lista pelo outro caminho.
    ops_cache.patch_chatwoot_elegiveis([lead])
    _relatorio_ve_elegivel("patch_chatwoot_elegiveis")
    print("smoke_ops_cache OK")


if __name__ == "__main__":
    main()
