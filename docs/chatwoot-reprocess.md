# Chatwoot + reprocessamento (Francisco)

## O que este bot já faz

1. Lê conversas abertas nas **contas dos clientes** (`CHATWOOT_ACCOUNTS`).
2. Detecta lead com última mensagem **incoming** há **>= 5 min** sem **outgoing** depois.
3. Só considera se o último incoming é **do dia corrente** (`America/Sao_Paulo` / `REPORT_TIMEZONE`). Dias anteriores são ignorados.
4. Se tem etiqueta `pausar_ia` (ou aliases) → **não reprocessa**, só reporta.
5. Se elegível → monta payload (com `account_id`, `inbox_id`, `link`) e (quando ligado) POST no Francisco.
6. Poller a cada `CHATWOOT_POLL_SECONDS` (default 60s) + seção no relatório diário.

Contas atuais (formato `Nome:accountId:inbox+inbox`). Sem inbox = skip até configurar:
tecnodiesel 34 (sem), AIASSOC 31→222+199, Hollytec 30→198, Sua marca 29→214, Clinic+ 26→165+186, Vai xorá 21→143, akila 20→118, espaço infinity 19→81, hile 18→77, astro 17→64+144, transfast 15 (sem), borelli 9→136, light 8→230, RHT 6→70, Infinity 1→112+113.

Link: `https://chat.iainfinity.com.br/app/accounts/{account_id}/inbox/{inbox_id}/conversations/{conversation_id}`


## Resposta à dúvida: dá pra saber o ERRO?

**Na maioria dos casos, não** — só com a API do Chatwoot.

| O que dá | O que não dá |
|----------|----------------|
| Lead sem resposta há X minutos | Stack trace / timeout / bug da IA |
| Se está com `pausar_ia` | Garantir o “porquê” sem log da IA |
| `causa_suspeita` se houver label/nota/atributo falando em erro | Inventar diagnóstico |

Conclusão: o fluxo confiável é **detectar silêncio → filtrar pausa → reprocessar**.  
Causa raiz só se o Francisco (ou a IA de atendimento) gravar isso em label/nota/log consultável.

## Pausa: Chatwoot vs Supabase

| Fonte | Papel no monitor |
|-------|------------------|
| Label Chatwoot `pausar_ia` | **Kill-switch oficial** para não reprocessar. Já cobrimos nas conversas **open**. |
| Tabelas Supabase (`*_pausar_ia` etc.) | Estado interno de **cada IA de atendimento**. Não é necessário para a regra “não mexer no humano”. |

**Gap real (bug de produto, não do Chatwoot sozinho):** ao **resolver/finalizar** a conversa, a label/pausa no Supabase frequentemente **não é limpa**. A IA de atendimento continua “pausada” no banco e o próximo contato não reativa.

Onde corrigir de verdade: webhook/`conversation_status_changed=resolved` na IA de atendimento → remover `pausar_ia` no Chatwoot **e** apagar/desativar a linha no Supabase.

O que o monitor pode fazer a mais (opcional):

1. **Sem Supabase:** varrer conversas `resolved`/`all` que ainda tenham `pausar_ia` → alerta “pausa órfã pós-finalização”.
2. **Com Supabase:** cruzar telefone/`contact_id` pausado no banco × status da conversa no Chatwoot → gap “pausado no Supa + conversa já resolvida”.

Supabase no monitor só vale a pena se tivermos URL/keys (ou view única) das pausas por cliente; senão Chatwoot label + alerta de órfãos já fecha o gap de relatório.

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
