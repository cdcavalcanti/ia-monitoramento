# API de Reprocessamento Automático (referência rápida)

Espelho resumido da doc oficial do Francisco (`docs/AUTOMATION_API.md`, **06/08/2026**).
Token **nunca** vai neste arquivo — só no `.env` (`REPROCESS_API_TOKEN`).

> Doc 06/08: **nada exige alteração no código do integrador**. Mudanças são do lado da API
> (1 conversa por vez na fila; motivos Chatwoot mais específicos; retry interno em 429).

## Acesso

| Item | Valor |
|------|--------|
| Base produção | `https://chat-reprocessor.vercel.app` |
| Health | `GET /health` (público) |
| Lote | `POST /api/reprocess/automatic` |
| Status | `GET /api/reprocess/automatic/status?queue_id=` |
| Auth | `Authorization: Bearer <REPROCESS_API_TOKEN>` |
| Worker | **não chamar** — interno (`REPROCESS_WORKER_TOKEN` / Supabase Cron) |

## Body do lote

```json
{
  "origem": "ia-monitoramento-infinity",
  "motivo": "silencio_ia",
  "leads": [
    {
      "account_id": 30,
      "conversation_id": 1507,
      "inbox_id": 198,
      "contact_id": 45,
      "telefone": "5511999999999",
      "elegivel_reprocessamento": true,
      "pausado": false
    }
  ]
}
```

- Obrigatórios por lead: `account_id`, `conversation_id` (inteiros positivos)
- Máx. **20** leads / request (o monitor chunka automaticamente)
- Timeout cliente recomendado: **≥ 30s** (nós usamos 60s no POST)
- Sucesso de transporte: **HTTP 202** — sempre ler `resultados[]`

## Status por item (resposta do lote)

| Status | Significado |
|--------|-------------|
| `enfileirado` | Guardar `queue_id` e acompanhar |
| `ignorado` | Situação normal — ver `motivo` |
| `erro` | Ver `motivo` + `temporario` (true → pode tentar de novo no próximo ciclo) |

### Motivos `ignorado` mais comuns

`ja_processado` · `ja_respondido` · `pausar_ia` · `cliente_nao_configurado` · `fora_do_dia_atual` · `aguardando_threshold` · `conversa_nao_aberta`

`ja_processado` agora também cobre: **já tem item `pending`/`running` da mesma conversa** (máx. 1 por vez).

### Motivos `erro` (Chatwoot)

`chatwoot_timeout` · `chatwoot_rate_limited` · `chatwoot_network_error` · `chatwoot_http_error` · `chatwoot_request_error`

## Status da fila (consulta)

`pending` → `running` → `success` | `canceled` | `error`

`canceled` = deixou de ser elegível na revalidação pré-n8n (não é bug).

## Reenvio (política)

| Situação | Reenviar? |
|----------|-----------|
| Rede / timeout / HTTP 5xx | Sim, com backoff |
| Item `temporario: true` | Sim, no próximo ciclo |
| HTTP 400 / 401 / 413 | **Não** |
| Item `ignorado` | **Não** |

Implementação: `app/services/reprocess.py` · guia ops: `docs/chatwoot-reprocess.md` · doc completa: `docs/AUTOMATION_API.md`.
