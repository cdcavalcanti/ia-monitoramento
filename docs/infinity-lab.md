# Infinity Lab — motor da IA de Monitoramento

O bot usa o agente da plataforma para **enriquecer** o relatório:

- Base: `https://infinity-lab.ai-infinity.io`
- Agente: `c797df225afa` (IA de Monitoramento)
- Modelo na plataforma: **Gemma 3 27B** (recomendado — relatório é síntese)
- Temperature sugerida no Lab: **0,2**
- Contexto sugerido: **8192+**
- Chunks RAG: **6**

## .env

```
INFINITY_LAB_BASE_URL=https://infinity-lab.ai-infinity.io
INFINITY_LAB_AGENT_ID=c797df225afa
INFINITY_LAB_API_KEY=inf_...
```

## Fluxo

1. Collectors agregam snapshot (Gestão / Hub / Chatwoot / WAHA)
2. `montar_relatorio` gera a **base factual** (números oficiais, sem inventar)
3. `infinity_lab.chat` recebe base + snapshot e **enriquece** em relatório consolidado
4. Se Lab falhar (5xx/timeout) → OpenAI fallback → se falhar, usa a base factual
5. PDF = Markdown da IA (`relatorio_para_pdf`) + KPIs determinísticos no topo

`OPENAI_API_KEY` permanece como fallback quando o Lab estiver fora.
