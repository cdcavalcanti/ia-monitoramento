# API de Reprocessamento Automático (referência)

Espelho da documentação oficial do chat-reprocessor (03/08/2026).
Token **nunca** vai neste arquivo — só no `.env` (`REPROCESS_API_TOKEN`).

## Acesso

| Item | Valor |
|------|--------|
| Base produção | `https://chat-reprocessor.vercel.app` |
| Health | `GET /health` (público) |
| Lote | `POST /api/reprocess/automatic` |
| Status | `GET /api/reprocess/automatic/status?queue_id=` |
| Auth | `Authorization: Bearer <REPROCESS_API_TOKEN>` |

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

- Obrigatórios por lead: `account_id`, `conversation_id`
- Máx. **20** leads por request (o monitor chunka automaticamente)
- Sucesso de transporte: **HTTP 202** — sempre ler `resultados[]`

## Status por item (resposta do lote)

| Status | Significado |
|--------|-------------|
| `enfileirado` | Guardar `queue_id` |
| `ignorado` | Ver `motivo` (`ja_processado`, `ja_respondido`, `pausar_ia`…) |
| `erro` | Ver `temporario` / `mensagem` |

## Status da fila (consulta)

`pending` → `running` → `success` | `canceled` | `error`

Doc completa no painel: `/documentacao` (após login).
Implementação local: `app/services/reprocess.py` + `docs/chatwoot-reprocess.md`.
