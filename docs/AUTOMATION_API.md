# API de Reprocessamento Automático

Documentação de integração da API que recebe conversas identificadas pela IA de monitoramento, valida a elegibilidade no Chatwoot e agenda o reprocessamento no fluxo correto do n8n.

Última atualização: 06/08/2026

> **Mudanças em 06/08/2026** — nada exige alteração no código do integrador.
>
> - Uma conversa passa a ter no máximo um item em processamento por vez. Envios de uma
>   conversa que já tem item ativo retornam `motivo: "ja_processado"`. Ver seção 6.
> - Falhas de consulta ao Chatwoot agora vêm com motivo específico
>   (`chatwoot_timeout`, `chatwoot_rate_limited`, ...) em vez de apenas
>   `chatwoot_request_error`. Ver seção 4.
> - A API passou a repetir automaticamente as chamadas ao Chatwoot em caso de `429` e
>   falhas temporárias, o que reduz itens com `status: "erro"`.

---

## 0. Leitura rápida

Se você só quer o essencial para começar, é isto:

**1. Enviar leads**

```http
POST https://chat-reprocessor.vercel.app/api/reprocess/automatic
Authorization: Bearer SEU_TOKEN
Content-Type: application/json

{ "leads": [ { "account_id": 30, "conversation_id": 1507 } ] }
```

Só `account_id` e `conversation_id` são obrigatórios. Máximo 20 leads por envio.

**2. Ler a resposta — atenção aqui**

`HTTP 202` significa "recebi e analisei", **não** "reprocessei todos".
Cada lead tem seu próprio resultado dentro de `resultados`:

```json
{
  "ok": true,
  "recebidos": 2, "aceitos": 1, "ignorados": 1, "erros": 0,
  "resultados": [
    { "conversation_id": 1507,  "status": "enfileirado", "queue_id": "cm123example" },
    { "conversation_id": 14242, "status": "ignorado", "motivo": "ja_respondido" }
  ]
}
```

**3. Acompanhar**

```http
GET /api/reprocess/automatic/status?queue_id=cm123example
Authorization: Bearer SEU_TOKEN
```

Até chegar em `success` (enviado ao n8n), `canceled` (deixou de ser elegível) ou
`error` (falhou).

**4. Os 4 erros que você mais vai ver**

| | O que é | O que fazer |
| --- | --- | --- |
| `401` | Token errado ou ausente | Corrigir. Não reenviar. |
| `400` | JSON ou campos inválidos | Corrigir. Não reenviar. |
| `413` | Mais de 20 leads | Dividir o lote. |
| `500`/`503` | Problema no servidor | Reenviar com espera. |

Detalhamento completo na **seção 7**.

---

## 1. Dados de acesso

Preencher estas informações antes de compartilhar o documento com o integrador:

| Informação | Valor |
| --- | --- |
| URL base de produção | `https://chat-reprocessor.vercel.app` |
| Ambiente de homologação | Não disponível, salvo indicação do responsável pela API |
| Token de integração | Enviar separadamente por um canal seguro |

Nunca inclua o token real nesta documentação ou no código-fonte da aplicação cliente.

## 2. Visão geral

O fluxo da integração é assíncrono:

1. O monitor envia um lote para `POST /api/reprocess/automatic`.
2. A API descarta o que dá para descartar sem custo: IDs inválidos, leads marcados como
   pausados, contas sem empresa configurada, e conversas que já têm item na fila.
3. Para o que sobrou, a API consulta o Chatwoot e valida cada lead novamente.
4. Os leads elegíveis entram em uma fila durável.
5. Um worker interno processa a fila. **Antes de enviar, ele valida tudo de novo** — a
   conversa pode ter mudado entre o enfileiramento e o processamento.
6. Se continuar elegível, o reprocessamento é enviado ao n8n.
7. O integrador pode consultar cada item pelo `queue_id` recebido.

> Por causa do passo 5, um item pode entrar na fila como `enfileirado` e terminar como
> `canceled`. Isso não é falha: significa que a conversa foi respondida ou fechada nesse
> intervalo, e o reprocessamento deixou de fazer sentido.

### Endpoints

| Método | Endpoint | Uso | Acesso |
| --- | --- | --- | --- |
| `GET` | `/health` | Verificar se o serviço está disponível | Público |
| `POST` | `/api/reprocess/automatic` | Enviar um lote para reprocessamento | Token da integração |
| `GET` | `/api/reprocess/automatic/status` | Consultar um item da fila | Token da integração |
| `GET` ou `POST` | `/api/reprocess/automatic/process` | Executar o worker da fila | Uso interno; não chamar na integração |

## 3. Autenticação

Os endpoints de envio e consulta aceitam um token técnico. O formato recomendado é:

```http
Authorization: Bearer <REPROCESS_API_TOKEN>
```

Também é aceito, por compatibilidade:

```http
X-Reprocess-Token: <REPROCESS_API_TOKEN>
```

Use somente um dos formatos por requisição. O token diferencia maiúsculas de minúsculas.

Quando o token estiver ausente ou incorreto, a API responderá `401 Unauthorized`:

```json
{
  "ok": false,
  "erro": "unauthorized",
  "mensagem": "Token técnico inválido ou ausente."
}
```

## 4. Enviar lote para reprocessamento

```http
POST /api/reprocess/automatic
Authorization: Bearer <REPROCESS_API_TOKEN>
Content-Type: application/json
```

### Limites

- O lote deve conter de 1 a 20 leads.
- O corpo completo da requisição não pode ultrapassar 1 MB.
- O limite de 20 leads é o valor padrão da aplicação e pode ser alterado pelo responsável da API.

### Corpo da requisição

#### Campos do lote

| Campo | Tipo | Obrigatório | Regra |
| --- | --- | --- | --- |
| `origem` | `string` | Não | Quando informado, deve ser exatamente `ia-monitoramento-infinity`. Esse também é o valor padrão. |
| `motivo` | `string` | Não | Motivo registrado para auditoria. Padrão: `silencio_ia`. |
| `leads` | `array` | Sim | Lista com pelo menos 1 lead. |

#### Campos de cada lead

| Campo | Tipo | Obrigatório | Uso |
| --- | --- | --- | --- |
| `account_id` | `integer` positivo | Sim | Identifica a conta no Chatwoot e a empresa configurada no reprocessador. |
| `conversation_id` | `integer` positivo | Sim | Identifica a conversa no Chatwoot. |
| `inbox_id` | `integer` positivo | Não | Se enviado, deve corresponder ao inbox real da conversa. |
| `contact_id` | `integer` positivo | Não | Se enviado, deve corresponder ao contato real da conversa. |
| `telefone` | `string` | Não | Usado como fallback se o telefone não estiver disponível no Chatwoot. Pode ser enviado sem `+` e sem formatação. |
| `pausado` | `boolean` | Não | Quando `true`, o item é ignorado sem reprocessamento. |
| `elegivel_reprocessamento` | `boolean` | Não | Quando `false`, o item é ignorado sem reprocessamento. |
| `account_nome` | `string` | Não | Mantido no payload para auditoria. |
| `nome` | `string` | Não | Mantido no payload para auditoria. |
| `labels` | `array` | Não | Mantido para auditoria; as etiquetas reais são consultadas novamente no Chatwoot. |
| `ultimo_incoming_em` | `string` ISO 8601 | Não | Mantido para auditoria; a data real é consultada novamente no Chatwoot. |
| `minutos_sem_resposta` | `number` | Não | Mantido para auditoria; o tempo real é recalculado pela API. |
| `status_conversa` | `string` | Não | Mantido para auditoria; o status real é consultado novamente no Chatwoot. |
| `link` | `string` | Não | Atalho da conversa mantido para auditoria. |
| `regra` | `string` | Não | Identificação da regra do monitor para auditoria. |
| `somente_hoje` | `boolean` | Não | Informativo. A API sempre exige que a última mensagem seja do dia atual. |
| `causa_suspeita` | `string` ou `null` | Não | Informação adicional para auditoria. |
| `causa_conhecida` | `boolean` | Não | Informação adicional para auditoria. |
| `fonte` | `string` | Não | Informação adicional para auditoria. |

Os únicos campos obrigatórios por lead são `account_id` e `conversation_id`. Dados enviados pelo monitor não substituem a validação feita diretamente no Chatwoot.

### Exemplo completo

```json
{
  "origem": "ia-monitoramento-infinity",
  "motivo": "silencio_ia",
  "leads": [
    {
      "motivo": "silencio_ia",
      "regra": "lead_sem_resposta_ia_gt_threshold_hoje",
      "somente_hoje": true,
      "elegivel_reprocessamento": true,
      "pausado": false,
      "account_id": 30,
      "account_nome": "Hollytec",
      "conversation_id": 1507,
      "inbox_id": 198,
      "contact_id": 45,
      "telefone": "5511999999999",
      "nome": "Nome do lead",
      "labels": [],
      "ultimo_incoming_em": "2026-08-03T18:00:00.000Z",
      "minutos_sem_resposta": 42.5,
      "causa_suspeita": null,
      "causa_conhecida": false,
      "status_conversa": "open",
      "link": "https://chat.example.com/app/accounts/30/conversations/1507",
      "fonte": "chatwoot"
    }
  ]
}
```

### Validações realizadas pela API

Antes de enfileirar, a API confirma diretamente no Chatwoot que:

- A conta está vinculada a uma empresa ativa e com webhook configurado.
- A conversa existe e está com status `open`.
- O `inbox_id` e o `contact_id`, quando enviados, correspondem à conversa.
- A conversa não possui `pausar_ia`, `pausar-ia`, `pause_ia` ou `ia_pausada`.
- Existe ao menos uma mensagem pública enviada pelo lead.
- Não existe mensagem pública da IA ou de um atendente depois da última mensagem do lead.
- A última mensagem do lead atingiu o tempo mínimo de silêncio, atualmente 5 minutos.
- A última mensagem do lead ocorreu no dia atual, usando o fuso `America/Sao_Paulo`.
- A mesma ocorrência de silêncio ainda não foi processada.
- A conversa não possui outro item ainda em processamento na fila (ver seção 6).

Todas essas validações são refeitas pelo worker imediatamente antes do envio ao n8n, mais
a checagem de pausa no Supabase. Uma conversa que deixou de ser elegível nesse intervalo
termina como `canceled`, e o motivo fica em `last_error`.

### Resposta aceita

Uma requisição válida retorna `202 Accepted`. Esse código confirma que o lote foi analisado, não que todos os itens foram reprocessados.

```json
{
  "ok": true,
  "recebidos": 2,
  "aceitos": 1,
  "ignorados": 1,
  "erros": 0,
  "resultados": [
    {
      "conversation_id": 1507,
      "status": "enfileirado",
      "queue_id": "cm123example",
      "idempotency_key": "auto-0123456789abcdef0123456789abcdef01234567"
    },
    {
      "conversation_id": 14242,
      "status": "ignorado",
      "motivo": "ja_respondido",
      "mensagem": "Já existe resposta da IA ou de um atendente após a última mensagem do lead.",
      "detalhes": null
    }
  ]
}
```

### Status por item na resposta do lote

| Status | Significado | Ação recomendada |
| --- | --- | --- |
| `enfileirado` | O lead foi validado e entrou na fila. | Guardar o `queue_id` e consultar o status. |
| `ignorado` | O lead não atende mais às regras ou já foi recebido antes. | Verificar `motivo`; não reenviar sem mudança na conversa. |
| `erro` | Não foi possível validar esse lead. | Verificar `motivo`, `mensagem` e `temporario`. |

Um erro individual não altera o HTTP `202` do lote. Sempre leia o array `resultados` e os contadores da resposta.

### Motivos de item ignorado

| Motivo | Significado |
| --- | --- |
| `lead_invalido` | O item de `leads` não é um objeto JSON válido. |
| `ids_invalidos` | `account_id` ou `conversation_id` não é um inteiro positivo. |
| `pausar_ia` | O monitor marcou o lead como pausado ou a conversa possui uma etiqueta de pausa. |
| `marcado_inelegivel` | O monitor enviou `elegivel_reprocessamento: false`. |
| `cliente_nao_configurado` | A conta não está vinculada a uma empresa ativa com webhook. |
| `conversa_nao_aberta` | A conversa não está com status `open`. |
| `inbox_divergente` | O `inbox_id` enviado não corresponde ao Chatwoot. |
| `sem_mensagem_do_lead` | Não foi encontrada mensagem pública enviada pelo lead. |
| `ja_respondido` | A IA ou um atendente já respondeu após a última mensagem do lead. |
| `data_invalida` | A última mensagem não possui uma data válida. |
| `aguardando_threshold` | O tempo mínimo de silêncio ainda não foi atingido. |
| `fora_do_dia_atual` | A última mensagem do lead não ocorreu no dia atual. |
| `contato_divergente` | O `contact_id` enviado não corresponde ao Chatwoot. |
| `ja_processado` | A mesma ocorrência de silêncio já existe na fila, ou a conversa já possui um item em processamento. |

### Motivos de item com erro

Quando a consulta ao Chatwoot falha, o item retorna `status: "erro"`. A API tenta a
requisição novamente por conta própria antes de desistir, então um erro aqui significa
que as tentativas já se esgotaram.

| Motivo | Significado | `temporario` |
| --- | --- | --- |
| `chatwoot_timeout` | O Chatwoot não respondeu dentro do tempo limite. | `true` |
| `chatwoot_rate_limited` | O Chatwoot respondeu `429` mesmo após as tentativas com espera. | `true` |
| `chatwoot_network_error` | Falha de rede ao alcançar o Chatwoot. | `true` |
| `chatwoot_http_error` | O Chatwoot respondeu com um status de erro (por exemplo `404`, conversa inexistente). | `false` quando `404` |
| `chatwoot_request_error` | Falha não classificada na consulta ao Chatwoot. | `true` |

Itens com `temporario: true` podem ser reenviados mais tarde. Com `temporario: false`,
reenviar sem corrigir os dados vai falhar de novo.

## 5. Consultar status do item

Use preferencialmente o `queue_id` retornado no envio:

```http
GET /api/reprocess/automatic/status?queue_id=<QUEUE_ID>
Authorization: Bearer <REPROCESS_API_TOKEN>
```

Também é possível consultar pelo `request_id` depois que ele for atribuído:

```http
GET /api/reprocess/automatic/status?request_id=<REQUEST_ID>
Authorization: Bearer <REPROCESS_API_TOKEN>
```

### Resposta de sucesso

```json
{
  "ok": true,
  "item": {
    "id": "cm123example",
    "request_id": "d14e57d0-3dd3-4a69-aee5-c59af74534d7",
    "idempotency_key": "auto-0123456789abcdef0123456789abcdef01234567",
    "client": "hollytec",
    "conversation_id": 1507,
    "status": "success",
    "attempts": 1,
    "last_error": null,
    "enqueued_at": "2026-08-03T18:05:00.000Z",
    "claimed_at": "2026-08-03T18:05:12.000Z",
    "finished_at": "2026-08-03T18:05:14.000Z"
  }
}
```

### Status da fila

| Status | Significado |
| --- | --- |
| `pending` | Aguardando o worker ou uma nova tentativa. |
| `running` | Em processamento pelo worker. |
| `success` | O webhook foi aceito pelo n8n. Não significa, isoladamente, que a mensagem final já foi entregue ao lead. |
| `canceled` | O item deixou de ser elegível na validação feita imediatamente antes do envio. Consulte `last_error`. |
| `error` | O processamento falhou definitivamente após as tentativas permitidas. Consulte `last_error`. |

O campo `attempts` informa quantas vezes o worker tentou processar o item. Em falhas temporárias, o item volta para `pending` antes de uma nova tentativa.

Se o identificador não existir, a resposta será `404 Not Found`:

```json
{
  "ok": false,
  "erro": "queue_item_not_found",
  "mensagem": "Item de automação não encontrado."
}
```

## 6. Idempotência

A API cria uma chave usando:

- Origem da integração.
- Conta do Chatwoot.
- Conversa do Chatwoot.
- ID da última mensagem recebida do lead, ou a data dessa mensagem como fallback.

Reenviar o mesmo silêncio é seguro e retorna `motivo: "ja_processado"`, sem duplicar o efeito.

Se o lead enviar uma nova mensagem, uma nova chave é gerada e a conversa pode ser
reprocessada novamente, desde que continue elegível **e o item anterior daquela conversa
já tenha terminado**.

### Uma conversa por vez

Além da chave de idempotência, a API garante que cada conversa tenha no máximo um item
em processamento. Enquanto houver item `pending` ou `running` para a conversa, novos
envios dela retornam `motivo: "ja_processado"` com o `queue_id` do item em andamento.

Isso evita o seguinte cenário: o lead manda duas mensagens seguidas, o monitor envia as
duas ocorrências, e a segunda seria reprocessada porque a IA disparada pela primeira
ainda não teve tempo de responder no Chatwoot — resultando em dois reprocessamentos da
mesma conversa.

Assim que o item anterior chega a um estado final (`success`, `canceled` ou `error`), a
conversa volta a aceitar novos envios normalmente.

Não é necessário enviar um header de idempotência; a chave é calculada pela API.

## 7. Erros — guia completo

### 7.1 Os dois níveis de erro

Esta é a parte que mais causa confusão. **Erro de HTTP e erro de lead são coisas diferentes.**

```
┌─────────────────────────────────────────────────────────────┐
│  NÍVEL 1 — HTTP: a requisição inteira                       │
│  Deu 202? Então a requisição foi aceita e analisada.        │
│  Qualquer outro número = nenhum lead foi processado.        │
└─────────────────────────────────────────────────────────────┘
                             ↓  (se 202)
┌─────────────────────────────────────────────────────────────┐
│  NÍVEL 2 — item: cada lead dentro de `resultados`           │
│  Aqui cada lead tem seu próprio status, independente.       │
│  Um lead pode falhar enquanto os outros 19 entram na fila.  │
└─────────────────────────────────────────────────────────────┘
```

> **Regra de ouro:** `202` **não** significa "todos os leads foram reprocessados".
> Significa apenas "recebi seu lote e analisei cada lead". Sempre leia `resultados`.

Um lote com 20 leads em que todos foram rejeitados ainda retorna `202`, com
`"aceitos": 0`. Isso não é erro de integração — é resposta normal.

### 7.2 Tabela completa de status HTTP

| HTTP | Significado | Quando acontece | Reenviar? |
| --- | --- | --- | --- |
| `200` | OK | Consulta de status bem-sucedida, ou `GET /health`. | — |
| `202` | Aceito | Lote recebido e analisado. **Ler `resultados`.** | Não |
| `400` | Requisição malformada | JSON inválido, `leads` vazio ou ausente, `origem` diferente de `ia-monitoramento-infinity`, ou consulta sem `queue_id` nem `request_id`. | **Não** antes de corrigir |
| `401` | Não autenticado | Token ausente, incorreto, ou header mal formatado. | **Não** antes de corrigir |
| `404` | Não encontrado | `queue_id`/`request_id` inexistente, **ou** URL/método errados. | **Não** antes de corrigir |
| `413` | Corpo grande demais | Mais de 20 leads no lote, ou corpo acima de 1 MB. | **Não** — dividir o lote |
| `500` | Erro interno | Falha inesperada no servidor. | Sim, após alguns segundos |
| `502` `503` `504` | Serviço indisponível | Servidor fora do ar, sobrecarregado, ou `503 automation_not_configured` se o token não estiver configurado no servidor. | Sim, com backoff |

### 7.3 Detalhamento por código

#### `400 Bad Request`

```json
{ "ok": false, "erro": "automation_enqueue_failed", "mensagem": "Envie ao menos um lead no campo leads." }
```

Causas possíveis:

| `mensagem` | Como corrigir |
| --- | --- |
| `Body JSON inválido.` | O corpo não é JSON válido. Conferir serialização e o header `Content-Type: application/json`. |
| `Envie ao menos um lead no campo leads.` | `leads` ausente, vazio ou não é array. |
| `Body JSON inválido para reprocessamento automático.` | O corpo é um array ou um valor primitivo. Deve ser um objeto. |
| `A origem deve ser 'ia-monitoramento-infinity'.` | Campo `origem` com valor diferente. Omitir o campo também funciona. |

Na consulta de status:

```json
{ "ok": false, "erro": "identifier_required", "mensagem": "Informe queue_id ou request_id." }
```

**Nunca reenviar automaticamente um `400`.** A requisição vai falhar igual.

#### `401 Unauthorized`

```json
{ "ok": false, "erro": "unauthorized", "mensagem": "Token técnico inválido ou ausente." }
```

Checklist:

1. O header está presente? `Authorization: Bearer SEU_TOKEN`
2. Tem a palavra `Bearer` seguida de **um** espaço?
3. O token está completo, sem quebra de linha ou espaço no fim?
4. Maiúsculas e minúsculas conferem? **O token diferencia caixa.**
5. É o `REPROCESS_API_TOKEN`? O `REPROCESS_WORKER_TOKEN` é outro e não funciona aqui.

**Nunca reenviar automaticamente um `401`** — só gera ruído no log. Alerte um humano.

#### `403 Forbidden`

**Esta API nunca retorna `403`.** Se você receber um, ele não veio da aplicação.

Origem provável: proteção de deploy da Vercel, firewall, ou um proxy no meio do caminho.
Nesse caso o corpo normalmente **não é o JSON documentado aqui** — costuma ser HTML.

O que fazer: avisar o responsável pela API. Não é problema do seu código.

#### `404 Not Found`

Atenção: existem **dois** `404` com corpos diferentes.

**a) Item da fila não encontrado** — o `queue_id` ou `request_id` não existe:

```json
{ "ok": false, "erro": "queue_item_not_found", "mensagem": "Item de automação não encontrado." }
```

**b) URL ou método errados** — repare que as chaves mudam para `error`/`message`:

```json
{ "error": "not_found", "message": "Use GET /, GET /login, ..." }
```

Se você recebeu o formato (b), a causa quase sempre é uma destas:

- método errado (`GET` onde deveria ser `POST`)
- caminho com erro de digitação
- barra final sobrando

#### `413 Payload Too Large`

```json
{ "ok": false, "erro": "automation_enqueue_failed", "mensagem": "O lote excede o limite de 20 leads." }
```

Divida em lotes menores. O limite de corpo é 1 MB.

#### `500 Internal Server Error`

```json
{ "ok": false, "erro": "automation_enqueue_failed", "mensagem": "..." }
```

Falha inesperada. Pode reenviar após alguns segundos — a idempotência evita duplicação.
Se persistir por mais de alguns minutos, avise o responsável pela API.

Um caso específico tem formato diferente, com as chaves `success`/`error`/`message`:

```json
{
  "success": false,
  "error": "config_bootstrap_error",
  "message": "Variáveis obrigatórias ausentes: ...",
  "hint": "..."
}
```

Isso significa configuração faltando no servidor. Reenviar não adianta — avise o responsável.

#### `503 Service Unavailable`

```json
{ "ok": false, "erro": "automation_not_configured", "mensagem": "Defina REPROCESS_API_TOKEN no ambiente antes de usar esta rota." }
```

O token ainda não foi configurado no servidor. Não é problema do seu lado — avise o responsável.

Um `503` sem esse corpo JSON normalmente vem da infraestrutura, não da aplicação.

### 7.4 Os três formatos de corpo de erro

A API tem histórico e nem todos os erros usam as mesmas chaves. Trate os três:

| Formato | Chaves | Onde aparece |
| --- | --- | --- |
| **Automação** | `ok`, `erro`, `mensagem` | Todos os endpoints `/api/reprocess/automatic*` |
| **Rota inexistente** | `error`, `message` | `404` de URL/método errados |
| **Falha de bootstrap** | `success`, `error`, `message`, `hint` | `500 config_bootstrap_error` |

Leitura defensiva sugerida:

```js
const codigo = corpo.erro ?? corpo.error ?? "desconhecido";
const texto  = corpo.mensagem ?? corpo.message ?? "sem detalhe";
```

### 7.5 Árvore de decisão

```
Recebi uma resposta. E agora?
│
├─ Erro de rede / timeout / sem resposta
│  └─ REENVIAR com backoff. A idempotência protege contra duplicação.
│
├─ HTTP 202
│  └─ Percorrer `resultados`:
│     ├─ status "enfileirado" → guardar queue_id e consultar depois
│     ├─ status "ignorado"    → normal, não é erro. Ver `motivo` (seção 4)
│     └─ status "erro"        → ver `temporario`:
│                                ├─ true  → pode reenviar mais tarde
│                                └─ false → corrigir os dados antes
│
├─ HTTP 400 / 401 / 413
│  └─ NÃO reenviar. Corrigir a requisição. Alertar um humano.
│
├─ HTTP 404
│  └─ Corpo tem "erro"?   → identificador não existe
│     Corpo tem "error"?  → URL ou método errados
│
├─ HTTP 403
│  └─ Não vem desta API. Infraestrutura. Avisar o responsável.
│
└─ HTTP 500 / 502 / 503 / 504
   └─ REENVIAR com backoff (ex.: 5s, 15s, 60s).
      Persistindo, avisar o responsável.
```

### 7.6 Política de reenvio recomendada

| Situação | Reenviar? | Espera sugerida |
| --- | --- | --- |
| Timeout ou erro de rede | Sim | 5s, 15s, 60s |
| `500`, `502`, `503`, `504` | Sim | 5s, 15s, 60s |
| Item com `temporario: true` | Sim | No próximo ciclo do monitor |
| `400`, `401`, `403`, `413` | **Não** | Corrigir e alertar |
| Item `ignorado` | **Não** | Não é erro |
| Item com `temporario: false` | **Não** | Corrigir os dados |

Sugestão: no máximo 3 tentativas por lote, e pare de reenviar quando o mesmo erro
se repetir três vezes seguidas — nesse ponto é problema que precisa de gente olhando.

## 8. Exemplos de integração

### cURL

```bash
curl --request POST "https://chat-reprocessor.vercel.app/api/reprocess/automatic" \
  --header "Authorization: Bearer SEU_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "origem": "ia-monitoramento-infinity",
    "motivo": "silencio_ia",
    "leads": [
      {
        "account_id": 30,
        "conversation_id": 1507,
        "inbox_id": 198,
        "contact_id": 45,
        "telefone": "5511999999999"
      }
    ]
  }'
```

Consulta:

```bash
curl "https://chat-reprocessor.vercel.app/api/reprocess/automatic/status?queue_id=QUEUE_ID" \
  --header "Authorization: Bearer SEU_TOKEN"
```

### JavaScript

Exemplo com o tratamento de erro completo descrito na seção 7.

```js
const baseUrl = "https://chat-reprocessor.vercel.app";
const token = process.env.REPROCESS_API_TOKEN;

// Códigos em que reenviar NÃO adianta: a requisição precisa ser corrigida.
const NAO_REENVIAR = new Set([400, 401, 403, 413]);
const ESPERAS_MS = [5000, 15000, 60000];

function lerErro(corpo, status) {
  // A API tem três formatos de corpo de erro (ver seção 7.4).
  const codigo = corpo?.erro ?? corpo?.error ?? "desconhecido";
  const texto = corpo?.mensagem ?? corpo?.message ?? `Erro HTTP ${status}`;
  return { codigo, texto };
}

async function enviarLote(leads) {
  for (let tentativa = 0; tentativa <= ESPERAS_MS.length; tentativa += 1) {
    let response;

    try {
      response = await fetch(`${baseUrl}/api/reprocess/automatic`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          origem: "ia-monitoramento-infinity",
          motivo: "silencio_ia",
          leads,
        }),
      });
    } catch (erroRede) {
      // Timeout ou falha de rede: reenviar é seguro, a idempotência protege.
      if (tentativa === ESPERAS_MS.length) throw erroRede;
      await new Promise((r) => setTimeout(r, ESPERAS_MS[tentativa]));
      continue;
    }

    // O corpo pode não ser JSON quando o erro vem da infraestrutura (ex.: 403).
    const corpo = await response.json().catch(() => null);

    if (response.status === 202) {
      return corpo;
    }

    const { codigo, texto } = lerErro(corpo, response.status);

    if (NAO_REENVIAR.has(response.status)) {
      // Alertar um humano. Reenviar aqui só gera ruído.
      throw new Error(`[${response.status}/${codigo}] ${texto}`);
    }

    if (tentativa === ESPERAS_MS.length) {
      throw new Error(`[${response.status}/${codigo}] ${texto} (tentativas esgotadas)`);
    }

    await new Promise((r) => setTimeout(r, ESPERAS_MS[tentativa]));
  }
}

const resultado = await enviarLote([
  { account_id: 30, conversation_id: 1507, inbox_id: 198, contact_id: 45, telefone: "5511999999999" },
]);

// HTTP 202 nao garante que todo lead entrou: cada item tem status proprio.
for (const item of resultado.resultados) {
  switch (item.status) {
    case "enfileirado":
      console.log("na fila:", item.conversation_id, item.queue_id);
      break;
    case "ignorado":
      // Situacao normal, nao e falha. Ex.: ja_respondido, aguardando_threshold.
      console.log("ignorado:", item.conversation_id, item.motivo);
      break;
    case "erro":
      console.warn(
        item.temporario ? "erro temporario:" : "erro definitivo:",
        item.conversation_id,
        item.motivo,
        item.mensagem,
      );
      break;
  }
}
```

## 9. Estratégia recomendada para o integrador

### Envio

- Dividir envios maiores em lotes de no máximo 20 leads.
- Não enviar conversas marcadas como pausadas ou inelegíveis.
- Definir um timeout de cliente de pelo menos 30 segundos: o lote é validado no Chatwoot
  durante a requisição, então lotes grandes demoram mais.

### Leitura da resposta

- Considerar sucesso de transporte somente quando o HTTP for `202`.
- Mesmo com HTTP `202`, **sempre** percorrer `resultados` — cada lead tem status próprio.
- Tratar `ignorado` como situação normal, não como falha. Na maioria dos casos significa
  que a conversa deixou de precisar de reprocessamento entre a detecção e o envio.
- Guardar o `queue_id` de cada item `enfileirado`.

### Reenvio

- Repetir após timeout de rede ou HTTP `5xx`, com espera progressiva. A idempotência
  evita duplicação da mesma ocorrência.
- **Não** repetir automaticamente `400`, `401`, `403` ou `413` sem corrigir a requisição.
- Parar de reenviar após 3 falhas seguidas do mesmo tipo e alertar um humano.

### Acompanhamento

- Consultar o status em intervalos de 10 a 15 segundos, sem chamadas simultâneas para o
  mesmo item.
- Parar de consultar quando o item chegar a `success`, `canceled` ou `error` — esses são
  estados finais.
- O worker processa poucos itens por minuto. Um item recém-enfileirado pode ficar alguns
  minutos em `pending` se houver fila à frente — isso é normal. Já um item em `pending`
  por mais de 15 minutos com a fila vazia indica problema do lado da API. Vale alertar.

### O que logar

Para diagnóstico rápido quando algo der errado, registre por lead:
`conversation_id`, `queue_id`, `status`, `motivo` e o HTTP recebido. Com isso o
responsável pela API consegue rastrear o item ponta a ponta.

## 10. Agendamento do worker no Supabase

O worker interno não precisa de Cron na Vercel. A forma recomendada agora é agendar a chamada pelo Supabase Cron usando `pg_cron` + `pg_net`.

> O script completo e testado está em `documentation/SUPABASE_CRON.sql`. Prefira ele ao
> trecho abaixo, que é apenas ilustrativo.

### Secrets no Vault

Antes de criar o job, salve os valores sensíveis no Vault:

```sql
select vault.create_secret('https://chat-reprocessor.vercel.app', 'project_url');
select vault.create_secret('SEU_REPROCESS_WORKER_TOKEN', 'worker_token');
```

⚠️ **`create_secret` só cria.** Rodar de novo falha com
`duplicate key value violates unique constraint "secrets_name_idx"`. Para **trocar** um
segredo já existente, use `update_secret`:

```sql
select vault.update_secret(
  (select id from vault.secrets where name = 'worker_token'),
  'NOVO_TOKEN'
);
```

O `SUPABASE_CRON.sql` traz uma versão idempotente que cria ou sobrescreve conforme o caso.

### Job de agendamento

Crie um job para chamar o worker a cada minuto:

```sql
select cron.schedule(
  'chat-reprocessor-automatic-worker',
  '* * * * *',
  $$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url') || '/api/reprocess/automatic/process',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'worker_token')
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  ) as request_id;
  $$
);
```

⚠️ **`timeout_milliseconds` é obrigatório.** O default do `pg_net` é 5000 ms e o worker
não cabe nisso. Sem esse parâmetro o processamento até acontece — a função na Vercel roda
até o fim — mas a resposta se perde e `net._http_response` registra
`Timeout of 5000 ms reached` em vez do `{"ok":true,"processados":N}`. O worker vira uma
caixa-preta. O valor 60000 acompanha o `maxDuration` da função.

### Como verificar se está funcionando

⚠️ **`cron.job_run_details.status = 'succeeded'` não significa que o worker rodou.**
Significa apenas que o SQL foi executado. `net.http_post` é assíncrono — o resultado HTTP
real fica em outra tabela. Um cron pode reportar sucesso por dias enquanto o endpoint
devolve `401` a cada minuto.

A consulta que realmente responde se o worker está vivo:

```sql
select id, status_code, left(coalesce(content, ''), 300) as content, created
from net._http_response
order by id desc
limit 10;
```

| O que aparece | Significado |
| --- | --- |
| `200` com `{"ok":true,"processados":N}` | Funcionando. |
| `401 unauthorized` | O `worker_token` no Vault não bate com o `REPROCESS_WORKER_TOKEN` da Vercel. |
| `Timeout of 5000 ms reached` | Faltou `timeout_milliseconds` no `net.http_post`. |
| `503 automation_not_configured` | `REPROCESS_WORKER_TOKEN` não está definido no servidor. |

### Observações

- O endpoint suporta `GET` e `POST`, mas para o Supabase Cron o `POST` é a opção mais simples
- O worker continua processando a fila em lotes pequenos e com retry interno
- O token usado no cron deve ser o `REPROCESS_WORKER_TOKEN`, não o `REPROCESS_API_TOKEN`

## 11. Endpoint interno do worker

Esta seção é destinada somente à operação da API. O sistema integrador não precisa e não deve chamar este endpoint.

```http
GET /api/reprocess/automatic/process
Authorization: Bearer <REPROCESS_WORKER_TOKEN>
```

O mesmo endpoint também aceita `POST`. No modelo recomendado, ele é chamado automaticamente pelo Supabase Cron a cada minuto. Por padrão, processa até 3 itens por execução, permite até 3 tentativas por item e aplica reagendamento progressivo em falhas temporárias.

Exemplo de resposta:

```json
{
  "ok": true,
  "processados": 1,
  "resultados": [
    {
      "queue_id": "cm123example",
      "conversation_id": 1507,
      "status": "enviado",
      "request_id": "d14e57d0-3dd3-4a69-aee5-c59af74534d7"
    }
  ]
}
```

Os possíveis resultados do worker são `enviado`, `ignorado`, `reagendado` e `erro`.

## 12. Checklist antes de compartilhar

### Acesso

- Confirmar que a URL pública permanece `https://chat-reprocessor.vercel.app`.
- Confirmar que `GET /health` responde com HTTP `200`.
- Gerar ou confirmar um token exclusivo para o integrador.
- Enviar o token por um canal seguro, separado desta documentação.

### Empresas

- Confirmar que **toda empresa ativa tem `chatwoot_account_ids` preenchido**. A automação
  resolve a empresa exclusivamente por `account_id`; sem esse vínculo todo lead da conta
  volta como `cliente_nao_configurado`, mesmo com a empresa ativa e o webhook correto.

```sql
select nome, ativo, chatwoot_account_ids, url_webhook <> '' as tem_webhook
from "REPROCESSAMENTO - companies"
where ativo = true and chatwoot_account_ids = '[]'::jsonb;
-- deve retornar zero linhas
```

### Worker

- Confirmar que o Supabase Cron está agendando `POST /api/reprocess/automatic/process`.
- Confirmar que o `net.http_post` do job tem `timeout_milliseconds`.
- **Confirmar a resposta HTTP real, não o status do cron** (ver seção 10):

```sql
select status_code, left(coalesce(content, ''), 200) as content, created
from net._http_response order by id desc limit 5;
-- esperado: 200 com {"ok":true,"processados":N}
```

### Teste ponta a ponta

- Fazer um teste com uma única conversa real e elegível.
- Confirmar que o item chegou a `success` e que o fluxo foi concluído no n8n/Chatwoot.
- Confirmar que o `request_id` foi preenchido no item da fila.
