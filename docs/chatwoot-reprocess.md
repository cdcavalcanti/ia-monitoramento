# Chatwoot + reprocessamento (Francisco / chat-reprocessor)

## O que este bot faz

1. Lê conversas abertas nas **contas dos clientes** (`CHATWOOT_ACCOUNTS`).
2. Detecta lead com última mensagem **incoming** há **>= 5 min** sem **outgoing** depois.
3. Só considera se o último incoming é **do dia corrente** (`America/Sao_Paulo` / `REPORT_TIMEZONE`).
4. Se tem etiqueta `pausar_ia` (ou aliases) → **não reprocessa**, só reporta.
5. Se elegível → POST no **chat-reprocessor** (fila automática do Francisco).
6. Poller a cada `CHATWOOT_POLL_SECONDS` + botão **Reprocessar agora** no dash + seção no relatório.

## Contrato (validado em `IAINFINITY/chat-reprocessor`)

| Item | Valor |
|------|--------|
| Base | `https://chat-reprocessor.vercel.app` |
| Path | `/api/reprocess/automatic` |
| Método | `POST` |
| Auth | `Authorization: Bearer <REPROCESS_API_TOKEN>` **ou** `X-Reprocess-Token` |
| Sucesso | **HTTP 202** + `{ ok, aceitos, ignorados, erros, resultados[] }` |

Body:

```json
{
  "origem": "ia-monitoramento-infinity",
  "motivo": "silencio_ia",
  "leads": [
    {
      "motivo": "silencio_ia",
      "regra": "lead_sem_resposta_ia_gt_threshold_hoje",
      "account_id": 1,
      "account_nome": "Infinity",
      "conversation_id": 123,
      "inbox_id": 10,
      "contact_id": 45,
      "telefone": "5521999999999",
      "nome": "Fulano",
      "labels": [],
      "pausado": false,
      "elegivel_reprocessamento": true,
      "ultimo_incoming_em": "2026-08-04T12:00:00+00:00",
      "minutos_sem_resposta": 7.2,
      "status_conversa": "open",
      "link": "https://chat.iainfinity.com.br/app/accounts/1/inbox/10/conversations/123",
      "fonte": "chatwoot",
      "somente_hoje": true
    }
  ]
}
```

O Francisco **revalida** no Chatwoot (open, silêncio, pausa, dia) e enfileira com idempotência por mensagem.  
O monitor ainda faz **dedup local por dia** (`account_id:conversation_id:YYYY-MM-DD`) para não martelar o endpoint a cada tick.  
Lotes com mais de **20** leads são enviados em chunks automáticos.

Consulta de fila (após `status: enfileirado`):

```
GET /chatwoot/reprocessar/status?queue_id=<QUEUE_ID>
```

(proxy para `GET /api/reprocess/automatic/status` no Francisco).  
Não chamar `/api/reprocess/automatic/process` — é worker interno (`REPROCESS_WORKER_TOKEN` / Supabase Cron).

Doc espelho: `docs/api-reprocess-automatico.md`.

## Ligar no `.env`

```
CHATWOOT_HEALTH_ENABLED=true
CHATWOOT_API_TOKEN=...

REPROCESS_API_BASE_URL=https://chat-reprocessor.vercel.app
REPROCESS_PATH=/api/reprocess/automatic
REPROCESS_API_TOKEN=<mesmo REPROCESS_API_TOKEN do chat-reprocessor>
REPROCESS_ENABLED=true
```

O token precisa ser o `REPROCESS_API_TOKEN` configurado no deploy do **chat-reprocessor** (Vercel/env do Francisco).

## Smoke

```powershell
# só lista
Invoke-RestMethod -Method POST http://127.0.0.1:8000/chatwoot/reprocessar -ContentType application/json -Body '{"enviar":false}'

# envia lote
Invoke-RestMethod -Method POST http://127.0.0.1:8000/chatwoot/reprocessar -ContentType application/json -Body '{"enviar":true}'
```

Ou no dash: **Reprocessar agora**.

## Pausa: Chatwoot vs Supabase

| Fonte | Papel |
|-------|--------|
| Label Chatwoot `pausar_ia` | Kill-switch — monitor e Francisco respeitam |
| Supabase (`*_pausar_ia`) | Estado interno das IAs de atendimento — Francisco também checa no worker |

Gap de produto (pausa órfã pós-resolved) continua sendo da IA de atendimento, não deste monitor.
