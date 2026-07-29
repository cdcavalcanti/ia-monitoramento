"""Smoke da regra de silêncio Chatwoot — sem rede.

    python -m scripts.smoke_chatwoot_silence
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.collectors.chatwoot_health import analisar_conversa  # noqa: E402


def _ts(minutes_ago: float) -> float:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp()


def main() -> None:
    conv = {
        "id": 101,
        "inbox_id": 10,
        "status": "open",
        "labels": [],
        "meta": {"sender": {"id": 7, "name": "Lead Teste", "phone_number": "+5521999999999"}},
    }
    msgs_silencio = {
        "payload": [
            {"id": 1, "message_type": 0, "private": False, "content": "oi", "created_at": _ts(12)},
        ]
    }
    item = analisar_conversa(
        conv,
        msgs_silencio,
        silencio_minutos=5,
        pause_labels={"pausar_ia"},
        only_today=True,
        timezone_name="America/Sao_Paulo",
    )
    assert item is not None, "deveria detectar silêncio de hoje"
    assert item["elegivel_reprocessamento"] is True
    assert item["pausado"] is False
    assert item["somente_hoje"] is True
    assert item["causa_suspeita"] is None
    assert item["telefone"].endswith("99999999")

    # Mensagem de ontem: com only_today não entra
    msgs_ontem = {
        "payload": [
            {
                "id": 1,
                "message_type": 0,
                "private": False,
                "content": "oi",
                "created_at": _ts(60 * 30),  # ~30h atrás
            },
        ]
    }
    assert (
        analisar_conversa(
            conv,
            msgs_ontem,
            silencio_minutos=5,
            pause_labels={"pausar_ia"},
            only_today=True,
            timezone_name="America/Sao_Paulo",
        )
        is None
    ), "silêncio de dia anterior deve ser ignorado"

    # Sem filtro de dia, legado ainda pode ser elegível
    item_legado = analisar_conversa(
        conv,
        msgs_ontem,
        silencio_minutos=5,
        pause_labels={"pausar_ia"},
        only_today=False,
    )
    assert item_legado is not None
    assert item_legado["somente_hoje"] is False

    conv_pausa = {**conv, "labels": ["pausar_ia"]}
    item_p = analisar_conversa(
        conv_pausa,
        msgs_silencio,
        silencio_minutos=5,
        pause_labels={"pausar_ia"},
        only_today=True,
    )
    assert item_p is not None
    assert item_p["pausado"] is True
    assert item_p["elegivel_reprocessamento"] is False

    msgs_ok = {
        "payload": [
            {"id": 1, "message_type": 0, "private": False, "content": "oi", "created_at": _ts(12)},
            {"id": 2, "message_type": 1, "private": False, "content": "olá!", "created_at": _ts(11)},
        ]
    }
    assert analisar_conversa(conv, msgs_ok, silencio_minutos=5, pause_labels={"pausar_ia"}) is None

    msgs_recente = {
        "payload": [
            {"id": 1, "message_type": 0, "private": False, "content": "oi", "created_at": _ts(2)},
        ]
    }
    assert analisar_conversa(conv, msgs_recente, silencio_minutos=5, pause_labels={"pausar_ia"}) is None

    conv_erro = {**conv, "labels": ["erro_processamento"]}
    item_e = analisar_conversa(conv_erro, msgs_silencio, silencio_minutos=5, pause_labels={"pausar_ia"})
    assert item_e is not None
    assert item_e["causa_suspeita"] and "label:" in item_e["causa_suspeita"]

    print("smoke_chatwoot_silence OK")


if __name__ == "__main__":
    main()
