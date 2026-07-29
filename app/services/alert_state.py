"""Estado em memória para alertar só na TRANSICAO (evita spam a cada poll).

Primeira observação de cada chave = baseline (não alerta).
Assim um restart do serviço não dispara dezenas de WhatsApps
por sessões que já estavam FAILED.
"""

from __future__ import annotations

from typing import Any


class AlertState:
    def __init__(self) -> None:
        # chave -> último status conhecido (ex.: "ok:WORKING", "ruim:FAILED")
        self._last: dict[str, str] = {}

    def observar(self, chave: str, status_atual: str) -> bool:
        """Registra status. True só se mudou em relação a um valor já conhecido."""
        prev = self._last.get(chave)
        self._last[chave] = status_atual
        if prev is None:
            return False  # baseline — sem alerta
        return prev != status_atual

    # alias legado
    def mudou(self, chave: str, status_atual: str) -> bool:
        return self.observar(chave, status_atual)

    def conhecido(self, chave: str) -> bool:
        return chave in self._last

    def snapshot(self) -> dict[str, str]:
        return dict(self._last)


alert_state = AlertState()
