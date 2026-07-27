"""Gera o relatório diário pelo terminal.

    python -m scripts.gerar_relatorio_cli
    python -m scripts.gerar_relatorio_cli --sem-envio
    python -m scripts.gerar_relatorio_cli --print

Precisa de RELATORIO_API_TOKEN. OPENAI_API_KEY opcional (fallback sem LLM).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from app.services.pipeline import gerar_relatorio_diario  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-envio", action="store_true", help="não envia WhatsApp")
    parser.add_argument("--print", dest="do_print", action="store_true", help="imprime o markdown")
    args = parser.parse_args()

    resultado = await gerar_relatorio_diario(enviar=not args.sem_envio, forcar=True)
    print("ok:", resultado["paths"])
    print("fontes:", resultado["fontes"])
    print("alertas:", resultado["alertas"])
    print("whatsapp:", resultado["enviado_whatsapp"])
    if args.do_print:
        print("\n" + resultado["relatorio_md"])


if __name__ == "__main__":
    asyncio.run(main())
