"""Configuração. Fonte de verdade das variáveis de ambiente.

Se você adicionar uma var aqui, adicione no .env.example junto — senão o
.env.example vira documentação mentirosa.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- OpenAI ----
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o"

    # ---- Gestão Infinity ----
    gestao_api_base_url: str = "https://gestao-infinity.ai-infinity.io"
    relatorio_api_token: str = ""

    # ---- Painel de Serviços (fase 2) ----
    painel_api_base_url: str = ""
    painel_api_token: str = ""
    painel_enabled: bool = False

    # ---- Chatwoot saúde das IAs ----
    chatwoot_base_url: str = "https://chat.iainfinity.com.br"
    chatwoot_account_id: str = "1"
    chatwoot_api_token: str = ""
    chatwoot_health_enabled: bool = False
    # Inbox opcional (conta compartilhada). Vazio = todas as inboxes da conta.
    chatwoot_inbox_id: str = ""
    # Lead sem resposta da IA há mais que N minutos → candidato a reprocessar.
    chatwoot_silence_minutes: float = 5.0
    # Poller contínuo (só se health_enabled). 0 = desliga o poller.
    chatwoot_poll_seconds: float = 60.0
    chatwoot_max_pages: int = 5
    chatwoot_max_conversations: int = 80
    # Etiquetas que bloqueiam reprocessamento (separadas por vírgula).
    chatwoot_pause_labels: str = "pausar_ia,pausar-ia,pause_ia,ia_pausada"

    # ---- Sistema de reprocessamento (Francisco) ----
    # Endpoints definitivos chegam com o mapeamento dele. Até lá: stub seguro.
    reprocess_api_base_url: str = ""
    reprocess_api_token: str = ""
    reprocess_enabled: bool = False
    # Path relativo ao base_url. Ajustar quando o map chegar.
    reprocess_path: str = "/api/reprocessar"

    # ---- WAHA (entrega + saúde de sessões) ----
    waha_url: str = ""
    waha_token: str = ""
    waha_session: str = "ALPHA_TESTE"
    notify_whatsapp_to: str = ""
    # Monitora GET /api/sessions e alerta mudança de status.
    waha_health_enabled: bool = False

    # ---- alertas 24h (Painel + WAHA) ----
    alert_poller_enabled: bool = True
    alert_poll_seconds: float = 60.0

    # ---- agendamento de RELATÓRIOS (não é o poller 24h) ----
    # Vários horários: "08:00,18:00"
    report_times: str = "08:00,18:00"
    report_hour: int = 8
    report_minute: int = 0
    report_timezone: str = "America/Sao_Paulo"
    scheduler_enabled: bool = True
    monitor_enabled: bool = True

    # ---- storage local ----
    data_dir: Path = Path("data")
    sqlite_path: Path = Path("data/monitoramento.db")

    @field_validator(
        "gestao_api_base_url",
        "painel_api_base_url",
        "chatwoot_base_url",
        "waha_url",
        "reprocess_api_base_url",
        mode="before",
    )
    @classmethod
    def _strip_slash(cls, v: object) -> object:
        return v.rstrip("/") if isinstance(v, str) else v

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "relatorios").mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def gestao_enabled(self) -> bool:
        return bool(self.gestao_api_base_url and self.relatorio_api_token)

    @property
    def delivery_whatsapp_enabled(self) -> bool:
        return bool(self.waha_url and self.waha_token and self.notify_whatsapp_to)

    @property
    def pause_labels(self) -> list[str]:
        return [x.strip() for x in str(self.chatwoot_pause_labels).split(",") if x.strip()]

    @property
    def reprocess_ready(self) -> bool:
        return bool(self.reprocess_enabled and self.reprocess_api_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
