# Conhecimento — API Gestão Infinity

Fonte: `gestao-infinity.ai-infinity.io`  
Auth: header `X-Relatorio-Token: <RELATORIO_API_TOKEN>`

## Endpoints

| Método | Path | Uso no relatório |
|--------|------|------------------|
| GET | `/api/tarefas` | atrasos, colunas, resumoStatus |
| GET | `/api/clientes` | Growth Tree |
| GET | `/api/clientes/:id` | carteira, % no prazo, risco |
| GET | `/api/clientes/:id/setores/:setorId` | projetos do setor |
| GET | `/api/projetos/:id` | tarefas por etapa + jornada |
| GET | `/api/projetos/:id/historico-progresso` | série de progresso |
| GET | `/api/pessoas/:id/planejamento` | plano da semana |
| GET | `/api/eficiencia` | eficiência do time |

## Notas

- A regra de atraso espelha o front (`backend/src/relatorio.ts`).
- `resumoStatus` só existe em tarefas concluídas após a mudança do campo obrigatório.
- Planejamento histórico: semântica planejado vs. realizado ainda em aberto com a plataforma.
