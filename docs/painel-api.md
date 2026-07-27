# Hub de Status Infinity (painel)

URL: https://painel-infinity.vercel.app  
Docs: https://painel-infinity.vercel.app/api/docs  
OpenAPI: `GET /api/openapi`

## Auth

- **Basic** (login do painel): `PAINEL_API_USER` + `PAINEL_API_PASSWORD`
- **Bearer** (máquina/IA): `Authorization: Bearer <PAINEL_API_TOKEN>`

## Endpoints

| Path | Uso no bot |
|------|------------|
| `GET /api/status/overview` | Poller de alertas 24h (leve) |
| `GET /api/relatorio-diario` | Relatório 08h/18h (agregador; cold start ~20–40s) |
| `GET /api/clientes` | Fallback / detalhe |
| `GET /api/clientes/{id}/servicos` | Infra por cliente |
| `GET /api/clientes/{id}/webhooks` | Automações |
| `GET /api/clientes/{id}/custo` | Custo de IA |

## Enums

- Cliente `health`: `operational | partial | offline`
- Serviço `status`: `online | offline | degraded`
- `saudeGeral`: `ok | atencao | critico`

## .env

```
PAINEL_API_BASE_URL=https://painel-infinity.vercel.app
PAINEL_API_USER=...
PAINEL_API_PASSWORD=...
PAINEL_ENABLED=true
```
