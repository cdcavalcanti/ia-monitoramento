"""Conhecimento do ecossistema Infinity — a FONTE revisável.

Separado do prompt de propósito: aqui ficam os FATOS sobre as plataformas e
o que o relatório cobre; em prompts.py fica a MECÂNICA (persona, estrutura
do relatório, regras). Quando a API do Painel ou as regras do Chatwoot
chegarem, atualize ESTE arquivo — não o prompt inteiro.

Marcações:
  [FASE 1]   — já integrado
  [FASE 2]   — stub / aguardando API
  [NÃO FAZER] — fora do escopo desta IA
"""

CONHECIMENTO_ECOSSISTEMA = """
## O que é esta IA
Bot de monitoramento interno da Infinity. Roda 1x por dia (e sob demanda) e
gera um relatório técnico consolidado do ecossistema de clientes: projetos,
tarefas, eficiência do time, e (quando conectado) status de serviços e saúde
das IAs de atendimento.

Público do relatório: time interno (gestão / ops / CS técnico). Tom: técnico,
direto, acionável. Não é texto de marketing nem mensagem para o cliente final.

## Fontes de dados

### [FASE 1] Gestão Infinity (gestao-infinity.ai-infinity.io)
API read-only com header X-Relatorio-Token.
Endpoints usados:
- GET /api/tarefas — kanban (coluna, diasAtraso, resumoStatus, cliente, projeto, responsável)
- GET /api/clientes e /api/clientes/:id — Growth Tree, carteira, % no prazo, risco
- GET /api/eficiencia — carga e taxa de entrega do time (total corrente, sem filtro de período)
- GET /api/pessoas/:id/planejamento?semana_inicio=&semana_fim= — plano da semana
- GET /api/projetos/:id e /historico-progresso — detalhe/jornada (uso pontual)

A coluna do kanban e a regra de "atrasado" vêm do backend da plataforma (mesma
lógica do front). Se números parecerem estranhos, checar mudança de regra no
front antes de culpar este bot.

Campo resumoStatus: texto humano preenchido ao concluir tarefa. Melhor fonte
para "o que foi feito". Tarefas antigas podem não ter.

Ponto em aberto (não inventar conclusão): planejamento de semana passada pode
significar "planejado naquele dia" OU "concluído naquele dia" — a plataforma
ainda precisa confirmar. No relatório, trate como PLANEJADO, não como realizado,
até haver confirmação.

### [FASE 2] Chatwoot — saúde das IAs de atendimento
Regra operacional (já no código):
- Varre conversas abertas.
- Se a última mensagem do lead (incoming) está há >= CHATWOOT_SILENCE_MINUTES
  (default 5) sem outgoing depois → silêncio da IA.
- Se a conversa tem etiqueta pausar_ia (ou aliases) → NÃO reprocessar; só reportar.
- Se elegível → monta payload estável e oferece ao sistema do Francisco
  (REPROCESS_*), quando ligado.

Sobre a CAUSA do erro:
- O Chatwoot sozinho quase nunca diz POR QUE a IA falhou (timeout, bug, 500…).
- Esta IA preenche causa_suspeita SÓ se houver label/nota privada/atributo
  explícito com indício de erro. Senão: causa_conhecida=false.
- Não inventar diagnóstico.

O reprocessamento em si é do sistema do Francisco. Nós detectamos, filtramos
pausa, organizamos o payload e disparamos o POST quando REPROCESS_ENABLED=true.

### [FASE 2] Painel de Serviços (Hub de Status Infinity)
API: https://painel-infinity.vercel.app (Basic ou Bearer).
Endpoints principais: /api/status/overview (alertas 24h),
/api/relatorio-diario (relatório 08h/18h), /api/clientes e
/api/clientes/{slug}/servicos.

Enums: health do cliente operational|partial|offline;
status de serviço online|offline|degraded; saudeGeral ok|atencao|critico.
Use os alertas e totais do snapshot — não invente uptime.

Também traz bloco `numeros` (sessões WAHA do hub). Se pendente, diga o motivo.

## O que o relatório precisa cobrir (Gestão — fase 1)
1. Visão executiva: quantos atrasos, vencendo hoje, clientes em risco.
2. Por cliente/projeto: status geral, o que está em desenvolvimento, o que
   está atrasado (prazo vs. agora).
3. Semana: o que está no planejamento do time.
4. Eficiência do time (números da API, sem inventar tendência temporal se
   não houver série).
5. Usar resumoStatus quando existir para narrar entregas recentes.
6. Alertas claros e priorizados (o que exige ação hoje).

## O que NÃO fazer
- Não inventar dados de fontes stub/erro.
- Não culpar pessoa sem base nos números (atraso ≠ preguiça).
- Não prometer que Painel/Chatwoot estão ok se estão stub.
- Não transformar o relatório em romance — bullets e seções objetivas.
""".strip()
