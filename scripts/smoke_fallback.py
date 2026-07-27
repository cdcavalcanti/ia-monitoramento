"""Smoke do fallback de relatório (sem OpenAI).

    python -m scripts.smoke_fallback
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.agent.graph import _fallback_sem_llm  # noqa: E402
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
                    "titulo": "Bug crítico",
                    "cliente": "Acme",
                    "projeto": "Core",
                    "responsavel": "Ana",
                    "coluna": "Atrasado",
                    "diasAtraso": 3,
                }
            ],
            "clientes": [{"id": 1, "nome": "Acme", "projetosEmRisco": 1}],
            "eficiencia": [],
            "planejamentos": [],
        },
    )
    snap = agregar(
        {
            "gestao": gestao,
            "painel": resultado_stub("painel-infinity", "stub"),
            "chatwoot": resultado_stub("chatwoot-ias", "stub"),
        }
    )
    md = _fallback_sem_llm(snap)
    assert "## 1. Resumo executivo" in md
    assert "## 2. Gestão Infinity" in md
    assert "Bug crítico" in md
    print("smoke_fallback OK")
    print(md[:500])


if __name__ == "__main__":
    main()
