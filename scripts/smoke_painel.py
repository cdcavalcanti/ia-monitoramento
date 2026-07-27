"""Smoke do normalizador do Hub de Status — sem rede.

    python -m scripts.smoke_painel
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.collectors.painel import normalizar_overview  # noqa: E402


def main() -> None:
    overview = {
        "saudeGeral": "atencao",
        "servicos": [
            {"name": "n8n", "url": "https://x", "status": "online", "ms": 10},
            {"name": "api", "url": "https://y", "status": "offline", "ms": None},
        ],
        "servicosComFalha": [{"name": "api", "url": "https://y", "status": "offline", "ms": None}],
        "alertas": ["1 serviço offline"],
        "numeros": {
            "pendente": False,
            "sessoes": [
                {"nome": "A", "status": "WORKING", "conectado": True},
                {"nome": "B", "status": "FAILED", "conectado": False, "numero": "55@c.us"},
            ],
        },
        "servidores": {"total": 2, "online": 2, "offline": 0},
        "clientes": {"total": 1, "operational": 0, "partial": 1, "offline": 0},
    }
    norm = normalizar_overview(overview)
    assert norm["saudeGeral"] == "atencao"
    assert len(norm["itens_alerta"]) >= 2  # api offline + sessao B
    nomes = {i["nome"] for i in norm["itens_alerta"]}
    assert "api" in nomes and "B" in nomes
    print("smoke_painel OK", nomes)


if __name__ == "__main__":
    main()
