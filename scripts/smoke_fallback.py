"""Smoke do fallback de relatório (sem OpenAI).

    python -m scripts.smoke_fallback
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.agent.graph import _fallback_sem_llm  # noqa: E402
from app.collectors.base import resultado_ok, resultado_stub  # noqa: E402
from app.services.aggregator import agregar  # noqa: E402
from app.services.delivery import _resumo_executivo  # noqa: E402


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
                    "coluna": {"id": "atrasado", "rotulo": "Atrasado"},
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
    # Mesma estrutura que o prompt pede à IA (app/agent/prompts.py), na ordem.
    secoes = [l for l in md.splitlines() if l.startswith("## ")]
    esperadas = ["## 1. Panorama", "## 2. Gestão por cliente", "## 3. Hub", "## 4. Chatwoot", "## 5. Plano", "## 6. Fontes"]
    assert len(secoes) == len(esperadas) and all(s.startswith(e) for s, e in zip(secoes, esperadas)), secoes
    assert "Bug crítico" in md
    # O resumo do WhatsApp sai da seção 1 — tem que carregar o atraso.
    assert "Atrasado" in _resumo_executivo(md), _resumo_executivo(md)
    print("smoke_fallback OK")
    print(md[:500])


if __name__ == "__main__":
    main()
