"""Smoke da varredura Chatwoot em paralelo — sem rede (httpx.MockTransport).

Confere: teto de requisições simultâneas, limite de conversas por conta, ordem
dos resultados, 429 com nova tentativa e 429 persistente contado como erro.

    python -m scripts.smoke_chatwoot_pool
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, ".")

from app.collectors import chatwoot_health as ch  # noqa: E402

TETO = 3


async def main() -> None:
    estado = {"ativos": 0, "pico": 0, "429_conv1": 0, "429_conv3": 0}
    atras = (datetime.now(timezone.utc) - timedelta(minutes=12)).timestamp()

    async def handler(req: httpx.Request) -> httpx.Response:
        estado["ativos"] += 1
        estado["pico"] = max(estado["pico"], estado["ativos"])
        try:
            await asyncio.sleep(0.02)
            partes = req.url.path.strip("/").split("/")
            if partes[-1] == "conversations":
                if req.url.params.get("page") != "1":
                    return httpx.Response(200, json={"data": {"payload": []}})
                convs = [{"id": i, "status": "open", "labels": [], "meta": {"sender": {"id": i}}} for i in range(1, 31)]
                return httpx.Response(200, json={"data": {"payload": convs}})
            if partes[-1] == "labels":
                return httpx.Response(200, json={"payload": []})
            cid = int(partes[-2])
            if cid == 1 and estado["429_conv1"] == 0:  # 429 uma vez: tem que tentar de novo
                estado["429_conv1"] += 1
                return httpx.Response(429, headers={"Retry-After": "0.01"})
            if cid == 3:  # 429 sempre: desiste e conta como erro
                estado["429_conv3"] += 1
                return httpx.Response(429, headers={"Retry-After": "0.01"})
            msgs = [{"message_type": 0, "content": "oi", "created_at": atras}]
            if cid % 2:  # ímpar: IA respondeu depois
                msgs.append({"message_type": 1, "content": "olá", "created_at": atras + 60})
            return httpx.Response(200, json={"payload": msgs})
        finally:
            estado["ativos"] -= 1

    loop = asyncio.get_running_loop()
    ch._pool = (loop, httpx.AsyncClient(transport=httpx.MockTransport(handler)), asyncio.Semaphore(TETO))

    res = await ch._varrer_conta(
        ch.ChatwootHealthClient("http://cw", "31", "tok"),
        account_nome="Teste",
        silencio=5,
        pause_labels=set(),
        skip_labels=set(),
        inbox_ids=["10"],
        max_pages=4,
        max_convs=20,
        base_url="http://cw",
        only_today=True,
        timezone_name="America/Sao_Paulo",
    )

    assert res["conversas_analisadas"] == 20, res["conversas_analisadas"]
    ids = [e["conversation_id"] for e in res["elegiveis"]]
    assert ids == list(range(2, 21, 2)), ids  # pares, na ordem da lista
    assert res["erros_ao_ler_mensagens"] == 1, res["erros_ao_ler_mensagens"]  # conv 3
    assert estado["429_conv1"] == 1 and estado["429_conv3"] == ch._TENTATIVAS_429, estado
    assert 1 < estado["pico"] <= TETO, estado  # paralelo de verdade, sem passar do teto
    print(f"smoke_chatwoot_pool OK (pico={estado['pico']}/{TETO})")


if __name__ == "__main__":
    asyncio.run(main())
