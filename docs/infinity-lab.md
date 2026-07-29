# Infinity Lab — motor da IA de Monitoramento

O bot **não** depende mais da OpenAI como caminho principal.
A síntese do relatório e o Q&A usam o agente da plataforma:

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
2. `infinity_lab.chat` envia o snapshot no `messages[].content`
3. System prompt + conhecimento ficam **no agente do Lab**
4. Resposta vem em JSON com campo `response`

`OPENAI_API_KEY` permanece só como fallback opcional.
