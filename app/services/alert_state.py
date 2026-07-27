"""Estado em memória para alertar só na TRANSICAO (evita spam a cada poll)."""

from __future__ import annotations

from typing import Any


class AlertState:
    def __init__(self) -> None:
        # chave -> último status conhecido (ex.: "WORKING", "down", "ok")
        self._last: dict[str, str] = {}

    def mudou(self, chave: str, status_atual: str) -> bool:
        prev = self._last.get(chave)
        self._last[chave] = status_atual
        if prev is None:
            # primeira leitura: só alerta se já estiver ruim
            return status_atual not in ("ok", "WORKING", "up", "online")
        return prev != status_atual

    def snapshot(self) -> dict[str, str]:
        return dict(self._last)


alert_state = AlertState()
