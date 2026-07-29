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

    # ---- Infinity Lab (GPU própria — Gemma/Qwen via Ollama) ----
    # Prioridade sobre OpenAI para síntese do relatório e Q&A.
    infinity_lab_base_url: str = "https://infinity-lab.ai-infinity.io"
    infinity_lab_agent_id: str = ""
    infinity_lab_api_key: str = ""

    # ---- OpenAI (fallback opcional se Lab estiver off) ----
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o"

    # ---- Gestão Infinity ----
    gestao_api_base_url: str = "https://gestao-infinity.ai-infinity.io"
    relatorio_api_token: str = ""

    # ---- Painel de Serviços / Hub de Status ----
    painel_api_base_url: str = "https://painel-infinity.vercel.app"
    painel_api_token: str = ""
    # Basic Auth (realm Hub de Status Infinity) — preferencial
    painel_api_user: str = ""
    painel_api_password: str = ""
    # Alternativa: user:senha numa linha só
    painel_basic_auth: str = ""
    painel_enabled: bool = False

    # ---- Chatwoot saúde das IAs ----
    chatwoot_base_url: str = "https://chat.iainfinity.com.br"
    # Fallback single-account (legado). Preferir CHATWOOT_ACCOUNTS.
    chatwoot_account_id: str = ""
    # Contas: "Nome:accountId:inbox+inbox,Nome:id:inbox"
    # Sem inboxes = conta listada mas ignorada até configurar (ex.: tecnodiesel:34).
    # Ex.: Clinic +:26:165+186,Hollytec:30:198
    chatwoot_accounts: str = ""
    chatwoot_api_token: str = ""
    chatwoot_health_enabled: bool = False
    # Inbox global legado (só se a conta não tiver inboxes em CHATWOOT_ACCOUNTS).
    chatwoot_inbox_id: str = ""
    # Lead sem resposta da IA há mais que N minutos → candidato a reprocessar.
    chatwoot_silence_minutes: float = 5.0
    # Só considera silêncio cujo último incoming é do dia corrente (timezone do REPORT).
    chatwoot_only_today: bool = True
    # Poller contínuo (só se health_enabled). 0 = desliga o poller.
    chatwoot_poll_seconds: float = 60.0
    # Limites POR CONTA (não globais).
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
        "infinity_lab_base_url",
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
    def infinity_lab_enabled(self) -> bool:
        return bool(self.infinity_lab_base_url and self.infinity_lab_agent_id and self.infinity_lab_api_key)

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
    def chatwoot_account_list(self) -> list[dict]:
        """Contas a varrer: [{id, nome, inbox_ids}, ...].

        Formato CHATWOOT_ACCOUNTS:
          Nome:accountId:inbox+inbox  (inboxes das IAs)
          Nome:accountId              (sem inbox → skip na coleta)
        """
        out: list[dict] = []
        raw = (self.chatwoot_accounts or "").strip()
        fallback_inbox = (self.chatwoot_inbox_id or "").strip()

        if raw:
            for parte in raw.split(","):
                parte = parte.strip()
                if not parte:
                    continue
                chunks = [c.strip() for c in parte.split(":")]
                inbox_ids: list[str] = []
                if len(chunks) >= 3:
                    # Nome pode ter ":"? improvável — usamos split simples:
                    # rsplit garante nome com espaços e último = inboxes, penúltimo = id
                    nome, aid, inboxes_raw = parte.rsplit(":", 2)
                    nome, aid = nome.strip(), aid.strip()
                    for tok in inboxes_raw.replace("|", "+").split("+"):
                        tok = tok.strip()
                        if tok:
                            inbox_ids.append(tok)
                elif len(chunks) == 2:
                    nome, aid = chunks[0], chunks[1]
                else:
                    nome, aid = parte, parte
                if not aid:
                    continue
                if not inbox_ids and fallback_inbox:
                    inbox_ids = [fallback_inbox]
                out.append({"id": aid, "nome": nome or aid, "inbox_ids": inbox_ids})
        elif (self.chatwoot_account_id or "").strip():
            aid = self.chatwoot_account_id.strip()
            inbox_ids = [fallback_inbox] if fallback_inbox else []
            out.append({"id": aid, "nome": aid, "inbox_ids": inbox_ids})
        return out

    @property
    def reprocess_ready(self) -> bool:
        return bool(self.reprocess_enabled and self.reprocess_api_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
