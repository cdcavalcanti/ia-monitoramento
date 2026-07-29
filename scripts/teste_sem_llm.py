"""Teste SEM gastar token de LLM.

Valida collectors reais (Gestao / Hub / Chatwoot / WAHA) + aggregator.
Nao chama Infinity Lab nem OpenAI.

    python -m scripts.teste_sem_llm
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app.services.aggregator import agregar  # noqa: E402


async def main() -> None:
    get_settings.cache_clear()
    s = get_settings()
    print("=== teste SEM LLM ===")
    print("slots:", s.report_times)
    print("flags: gestao", s.gestao_enabled, "| painel", s.painel_enabled, "| chatwoot", s.chatwoot_health_enabled, "| waha", s.waha_health_enabled)

    from app.collectors import gestao, painel, chatwoot_health, waha_health

    print("\n[1] Gestao...")
    g = await gestao.coletar()
    print("  status=", g["status"], end="")
    if g["status"] == "ok":
        d = g["dados"]
        print(f" tarefas={d.get('tarefas_total')} clientes={d.get('clientes_total')}")
    else:
        print(" ", d := g.get("dados"))

    print("[2] Hub de Status (overview leve)...")
    from app.collectors.painel import coletar_overview_leve

    p = await coletar_overview_leve()
    print("  status=", p["status"], end="")
    if p["status"] == "ok":
        tot = (p["dados"] or {}).get("totais") or {}
        print(f" saude={tot.get('saudeGeral')} problemas={tot.get('com_problema')}")
        alerts = ((p["dados"] or {}).get("normalizado") or {}).get("alertas_api") or []
        for a in alerts[:5]:
            print("   -", a)
    else:
        print(" ", p.get("dados"))

    print("[3] Chatwoot (silencio >5min)...")
    c = await chatwoot_health.coletar()
    print("  status=", c["status"], end="")
    if c["status"] == "ok":
        tot = (c["dados"] or {}).get("totais") or {}
        print(
            f" analisadas={c['dados'].get('conversas_analisadas')} "
            f"elegiveis={tot.get('elegiveis')} pausados={tot.get('pausados_com_silencio')}"
        )
    else:
        print(" ", c.get("dados"))

    print("[4] WAHA sessoes...")
    w = await waha_health.coletar()
    print("  status=", w["status"], end="")
    if w["status"] == "ok":
        tot = (w["dados"] or {}).get("totais") or {}
        print(f" total={tot.get('total')} working={tot.get('working')} ruins={tot.get('ruins')}")
    else:
        print(" ", w.get("dados"))

    print("\n[5] Aggregator (sem LLM)...")
    snap = agregar({"gestao": g, "painel": p, "chatwoot": c, "waha": w})
    print("  fontes:", {k: v.get("status") for k, v in (snap.get("fontes") or {}).items()})
    print("  alertas:")
    for a in (snap.get("alertas") or [])[:12]:
        print("   -", a)

    print("\nOK — collectors/aggregator sem gastar token de IA.")
    print("LLM (Lab/OpenAI) so entra em: gerar_relatorio_cli / POST /relatorio/gerar")


if __name__ == "__main__":
    asyncio.run(main())
