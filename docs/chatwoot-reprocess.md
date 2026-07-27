# Chatwoot + reprocessamento (Francisco)

## O que este bot já faz

1. Lê conversas abertas no Chatwoot.
2. Detecta lead com última mensagem **incoming** há **>= 5 min** sem **outgoing** depois.
3. Se tem etiqueta `pausar_ia` (ou aliases) → **não reprocessa**, só reporta.
4. Se elegível → monta payload e (quando ligado) POST no sistema do Francisco.
5. Poller a cada `CHATWOOT_POLL_SECONDS` (default 60s) + seção no relatório diário.

## Resposta à dúvida: dá pra saber o ERRO?

**Na maioria dos casos, não** — só com a API do Chatwoot.

| O que dá | O que não dá |
|----------|----------------|
| Lead sem resposta há X minutos | Stack trace / timeout / bug da IA |
| Se está com `pausar_ia` | Garantir o “porquê” sem log da IA |
| `causa_suspeita` se houver label/nota/atributo falando em erro | Inventar diagnóstico |

Conclusão: o fluxo confiável é **detectar silêncio → filtrar pausa → reprocessar**.  
Causa raiz só se o Francisco (ou a IA de atendimento) gravar isso em label/nota/log consultável.

## Payload que enviamos ao Francisco (contrato atual)

```json
{
  "origem": "ia-monitoramento-infinity",
  "motivo": "silencio_ia",
  "leads": [
    {
      "motivo": "silencio_ia",
      "regra": "lead_sem_resposta_ia_gt_threshold",
      "conversation_id": 123,
      "inbox_id": 10,
      "contact_id": 45,
      "telefone": "5521999999999",
      "nome": "Fulano",
      "labels": [],
      "pausado": false,
      "elegivel_reprocessamento": true,
      "ultimo_incoming_em": "2026-07-27T12:00:00+00:00",
      "minutos_sem_resposta": 7.2,
      "causa_suspeita": null,
      "causa_conhecida": false,
      "status_conversa": "open",
      "fonte": "chatwoot"
    }
  ]
}
```

`POST {REPROCESS_API_BASE_URL}{REPROCESS_PATH}`  
Headers: `Authorization: Bearer …` e `X-Reprocess-Token` (quando houver token).

## O que pedir ao Francisco (copiar)

Oi Francisco! Estou ligando a IA de monitoramento no teu reprocessador.

Já detecto no Chatwoot: lead >5 min sem resposta da IA e sem etiqueta `pausar_ia`.

Preciso que você me mande:

1. URL base da API de reprocessamento  
2. Token (se tiver)  
3. Path do endpoint (ex.: `/api/reprocessar`)  
4. Se o body acima serve ou quais campos você exige (nome exato)  
5. Resposta de sucesso esperada (status/JSON)

Assim que mandar, eu plugo no `.env` (`REPROCESS_*`) e ligo.

## O que você precisa no `.env` pra ligar a detecção

```
CHATWOOT_API_TOKEN=...
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_HEALTH_ENABLED=true
CHATWOOT_SILENCE_MINUTES=5
```

Reprocess automático (depois do map do Francisco):

```
REPROCESS_API_BASE_URL=...
REPROCESS_API_TOKEN=...
REPROCESS_ENABLED=true
REPROCESS_PATH=/api/reprocessar
```
