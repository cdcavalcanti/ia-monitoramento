# ia-monitoramento-infinity

Relatório diário automático do ecossistema Infinity: **projetos/tarefas (Gestão)**,
e em seguida (fase 2) **Painel de Serviços** + **saúde das IAs no Chatwoot**.

Espelha a arquitetura do `realdeal-sdr` (FastAPI + LangGraph/LangChain +
pydantic-settings + Docker), adaptada de atendimento conversacional para
**monitoramento e síntese de relatório**.

## Arquitetura

```
scheduler / POST /relatorio/gerar
        │
        ▼
 ┌──────────────┐   ┌─────────────┐   ┌──────────────────┐
 │ Gestão API   │   │ Painel API  │   │ Chatwoot health  │
 │ (fase 1 OK)  │   │ (stub)      │   │ (stub)           │
 └──────┬───────┘   └──────┬──────┘   └────────┬─────────┘
        └────────────┬─────┴───────────────────┘
                     ▼
              aggregator (determinístico)
                     ▼
              LLM síntese (Markdown)
                     ▼
         data/relatorios/YYYY-MM-DD.md|.json
                     │
                     └──► WAHA (opcional)
```

**Padrões herdados do SDR:**
- `conhecimento.py` = fatos; `prompts.py` = mecânica
- Classificação (atraso, totais, tops) **fora** do LLM
- Config = fonte de verdade sincronizada com `.env.example`
- Fail-open na entrega WhatsApp; relatório sempre salvo em disco
- Webhook/API não inventa dados de fonte stub

## Rodando local

```bash
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# preencha RELATORIO_API_TOKEN e OPENAI_API_KEY
```

Smokes sem rede:

```bash
.\.venv\Scripts\python -m scripts.smoke_aggregator
.\.venv\Scripts\python -m scripts.smoke_fallback
```

Smoke com a API de Gestão (precisa token):

```bash
.\.venv\Scripts\python -m scripts.smoke_gestao
```

Gerar relatório agora:

```bash
.\.venv\Scripts\python -m scripts.gerar_relatorio_cli --sem-envio --print
```

Subir o serviço:

```bash
docker compose up -d --build
# UI ops (dash + chat):
# http://127.0.0.1:8010/
curl http://127.0.0.1:8010/health
curl -X POST http://127.0.0.1:8010/relatorio/gerar -H "Content-Type: application/json" -d "{\"enviar\":false}"
```

Local sem Docker:

```bash
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## Endpoints

| Método | Rota | Uso |
|--------|------|-----|
| GET | `/` | **UI** — dash de métricas + chat |
| GET | `/health` | config carregada |
| GET | `/ops/status` | fontes, scheduler, último relatório |
| GET | `/ops/metrics` | tokens/gasto do dia + reprocess capturados/enviados |
| POST | `/relatorio/gerar` | gera agora (`enviar`, `forcar`) |
| GET | `/relatorio/ultimo` | último markdown + alertas |
| GET | `/chatwoot/leads-silencio` | elegíveis de hoje (inboxes IA) |
| POST | `/chatwoot/reprocessar` | detecta + (se ligado) envia ao Francisco |
| POST | `/perguntar` | Q&A (Infinity Lab / OpenAI) |

## Variáveis importantes

| Var | Função |
|-----|--------|
| `RELATORIO_API_TOKEN` | token `X-Relatorio-Token` do Gestão |
| `GESTAO_API_BASE_URL` | default `https://gestao-infinity.ai-infinity.io` |
| `OPENAI_API_KEY` | síntese LLM (sem key = fallback estruturado) |
| `REPORT_HOUR` / `REPORT_MINUTE` | horário do job (TZ `America/Sao_Paulo`) |
| `SCHEDULER_ENABLED` | `false` = só sob demanda |
| `PAINEL_*` / `CHATWOOT_HEALTH_ENABLED` | fase 2 |
| `NOTIFY_WHATSAPP_TO` + `WAHA_*` | entrega do resumo |

## Reprocessamento (Chatwoot → Francisco)

Detecção de silêncio neste monitor → `POST` em `https://chat-reprocessor.vercel.app/api/reprocess/automatic`.

No `.env`: `REPROCESS_API_TOKEN` (mesmo do chat-reprocessor) + `REPROCESS_ENABLED=true`.

Dash: botão **Reprocessar agora**. Doc: `docs/chatwoot-reprocess.md`.
