"""Smoke opcional da API de Gestão (precisa de rede + token).

    python -m scripts.smoke_gestao

Lê RELATORIO_API_TOKEN / GESTAO_API_BASE_URL do .env.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.collectors.gestao import GestaoClient, coletar  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main() -> None:
    s = get_settings()
    if not s.gestao_enabled:
        print("SKIP: configure RELATORIO_API_TOKEN no .env")
        return

    client = GestaoClient(s.gestao_api_base_url, s.relatorio_api_token)
    tarefas = await client.listar_tarefas()
    clientes = await client.listar_clientes()
    print("tarefas tipo:", type(tarefas).__name__, "clientes tipo:", type(clientes).__name__)

    resultado = await coletar()
    print("coleta status:", resultado["status"])
    if resultado["status"] == "ok":
        d = resultado["dados"]
        print("tarefas:", d.get("tarefas_total"), "clientes:", d.get("clientes_total"))
        print("semana:", d.get("semana_inicio"), "->", d.get("semana_fim"))
    else:
        print("dados:", resultado["dados"])
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
