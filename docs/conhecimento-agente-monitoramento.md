# Conhecimento — IA de Monitoramento Infinity

Público: time interno (ops, gestão, CS técnico). Tom técnico. Não é atendimento ao cliente final.

## O que esta IA faz

Gera relatório técnico consolidado do ecossistema Infinity (projetos, serviços, IAs de atendimento) e apoia alertas 24h. Relatórios principais às 08h e 18h (America/Sao_Paulo). Alertas de queda de serviço/sessão e silêncio de IA rodam o tempo todo.

## Fontes de dados

### 1) Gestão Infinity (gestao-infinity.ai-infinity.io)

API read-only com header `X-Relatorio-Token`.

Endpoints usados pelo bot:
- GET /api/tarefas — coluna do kanban, diasAtraso, resumoStatus, cliente, projeto, responsável
- GET /api/clientes e GET /api/clientes/:id — carteira, % no prazo, progresso, projetos em risco
- GET /api/eficiencia — carga e taxa de entrega do time (total corrente)
- GET /api/pessoas/:id/planejamento?semana_inicio=&semana_fim= — plano da semana
- GET /api/projetos/:id e /historico-progresso — detalhe e evolução de progresso

Regras importantes:
- A classificação de "atrasado" e a coluna do kanban espelham o front da plataforma. Se um número parecer estranho, checar mudança de regra no Gestão antes de culpar o bot.
- `resumoStatus` é texto humano preenchido ao concluir tarefa. Melhor fonte para narrar "o que foi feito". Tarefas antigas podem não ter o campo.
- Planejamento semanal: tratar como PLANEJADO, não como realizado, até a plataforma confirmar a semântica de semanas passadas.

Uso no relatório:
- totais (tarefas, atrasadas, em desenvolvimento, vencimento hoje, aguardando cliente)
- top atrasos (cliente · projeto · tarefa · responsável · dias)
- clientes em risco / % no prazo
- planejamento da semana por pessoa
- eficiência do time
- entregas recentes com resumoStatus

### 2) Hub de Status / Painel Infinity (painel-infinity.vercel.app)

Auth: HTTP Basic (login do painel) ou Bearer token de máquina.

Endpoints:
- GET /api/status/overview — visão leve (alertas 24h)
- GET /api/relatorio-diario — agregador para o relatório (cold start pode levar 20–40s)
- GET /api/clientes
- GET /api/clientes/{slug}/servicos
- GET /api/clientes/{slug}/webhooks
- GET /api/clientes/{slug}/custo
- GET /api/openapi — especificação

Enums estáveis:
- health do cliente: `operational` | `partial` | `offline`
- status de serviço HTTP: `online` | `offline` | `degraded`
- saudeGeral: `ok` | `atencao` | `critico`

Uso no relatório / alertas:
- saudeGeral
- servidores online/offline
- serviços HTTP com falha (nome, status, ms, url)
- clientes partial/offline (webhooks inativos)
- bloco `numeros` (sessões WAHA do hub) — se `pendente=true`, reportar o motivo
- `alertas` vindos da própria API do hub
- custo de IA só se vier no snapshot (não inventar)

Nunca inventar uptime ou status de serviço ausente no snapshot.

### 3) WAHA (instâncias WhatsApp)

Monitora sessões via API WAHA (`GET /api/sessions`).

Status:
- `WORKING` = ok
- `FAILED`, `STOPPED`, `SCAN_QR_CODE`, `BROKEN` = problema

Alertas: notificar no WhatsApp na TRANSICAO (caiu / recuperou), não spam a cada minuto com o mesmo estado.

Entrega do relatório também pode sair por WAHA para o número configurado em `NOTIFY_WHATSAPP_TO`.

### 4) Chatwoot — saúde das IAs de atendimento

Regra operacional de silêncio:
1. Conversas abertas
2. Última mensagem do lead (incoming, não privada) há >= 5 minutos
3. Sem mensagem outgoing depois dela
4. Se a conversa tem etiqueta `pausar_ia` (ou aliases: pausar-ia, pause_ia, ia_pausada) → NÃO reprocessar; só reportar
5. Se elegível → montar payload e oferecer ao sistema de reprocessamento do Francisco (quando ligado)

Sobre a CAUSA do erro:
- O Chatwoot sozinho quase nunca traz o motivo técnico (timeout, bug, 500).
- `causa_suspeita` só deve ser preenchida com evidência (label, nota privada ou atributo falando em erro).
- Sem evidência: `causa_conhecida=false`. Não inventar diagnóstico.

Reprocessamento automático NÃO é feito por esta IA de monitoramento. Ela detecta, filtra pausa e sinaliza. A execução é do serviço do Francisco.

## Estrutura obrigatória do relatório (Markdown)

1. Resumo executivo
2. Gestão Infinity — Projetos e tarefas
3. Hub de Status (Painel)
3.1 WAHA (instâncias)
4. Chatwoot / IAs de atendimento
5. Ações recomendadas (P0 / P1 / P2)
6. Fontes e lacunas

## Como priorizar ações

- P0: atrasos críticos, vencimento hoje, serviço/sessão fora, leads elegíveis a reprocessar sem pausar_ia, saudeGeral critico
- P1: clientes partial com muitos webhooks inativos, alertas do hub, planejamento sobrecarregado
- P2: melhorias, fontes ainda incompletas, causa de erro ainda desconhecida

## O que NÃO fazer

- Inventar dados de fonte stub, erro ou ausente
- Culpar pessoa sem base nos números (atraso ≠ preguiça)
- Prometer que Painel/Chatwoot/WAHA estão ok se o snapshot não confirmar
- Transformar o relatório em romance ou marketing
- Devolver JSON cru no lugar do relatório
- Indicar reprocessamento de lead com `pausar_ia`

## Repositórios do bot

- Pessoal: https://github.com/cdcavalcanti/ia-monitoramento
- Infinity: https://github.com/IAINFINITY/qa-ia-monitoramento

## Motor de síntese

Agente na Infinity Lab (GPU própria / Ollama). Modelo recomendado: Gemma 3 27B. Temperature baixa (0.2) para fatos. O system prompt fica na configuração do agente; este documento é o conhecimento (RAG).
