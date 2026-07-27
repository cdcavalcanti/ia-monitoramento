"""Smoke do aggregator — sem rede.

    python -m scripts.smoke_aggregator
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.collectors.base import resultado_ok, resultado_stub  # noqa: E402
from app.services.aggregator import agregar  # noqa: E402


def main() -> None:
    gestao = resultado_ok(
        "gestao-infinity",
        {
            "semana_inicio": "2026-07-20",
            "semana_fim": "2026-07-26",
            "tarefas": [
                {
                    "titulo": "Integrar webhook",
                    "cliente": "Acme",
                    "projeto": "IA Atendimento",
                    "responsavel": "Ana",
                    "coluna": "Atrasado",
                    "diasAtraso": 5,
                },
                {
                    "titulo": "Ajustar prompt",
                    "cliente": "Acme",
                    "projeto": "IA Atendimento",
                    "responsavel": "Ana",
                    "coluna": "Desenvolvimento",
                    "diasAtraso": 0,
                },
                {
                    "titulo": "Validar LP",
                    "cliente": "Beta",
                    "projeto": "Landing",
                    "responsavel": "Bruno",
                    "coluna": "Vencimento Hoje",
                },
                {
                    "titulo": "Entrega X",
                    "cliente": "Beta",
                    "projeto": "Landing",
                    "responsavel": "Bruno",
                    "coluna": "Concluído",
                    "resumoStatus": "Subiu LP e pediu ok do cliente.",
                },
            ],
            "clientes": [
                {"id": 1, "nome": "Acme", "projetosEmRisco": 2, "pctNoPrazo": 40, "progressoMedio": 55},
                {"id": 2, "nome": "Beta", "projetosEmRisco": 0, "pctNoPrazo": 90, "progressoMedio": 80},
            ],
            "eficiencia": [
                {"nome": "Ana", "tarefasAtrasadas": 1, "taxaEntrega": 70},
                {"nome": "Bruno", "tarefasAtrasadas": 0, "taxaEntrega": 95},
            ],
            "planejamentos": [
                {
                    "pessoa": "ana",
                    "nome": "Ana",
                    "planejamento": {"segunda": [{"titulo": "Integrar webhook"}], "terca": []},
                }
            ],
        },
    )
    painel = resultado_stub("painel-infinity", "ainda não conectado")
    chatwoot = resultado_stub("chatwoot-ias", "ainda não conectado")

    snap = agregar({"gestao": gestao, "painel": painel, "chatwoot": chatwoot})
    assert snap["gestao"]["totais"]["atrasadas"] == 1, snap["gestao"]["totais"]
    assert snap["gestao"]["totais"]["vencimento_hoje"] == 1
    assert snap["gestao"]["totais"]["em_desenvolvimento"] >= 1
    assert any("atrasada" in a.lower() for a in snap["alertas"])
    assert snap["fontes"]["painel"]["status"] == "stub"
    print("smoke_aggregator OK")
    print("totais:", snap["gestao"]["totais"])
    print("alertas:", snap["alertas"])


if __name__ == "__main__":
    main()
