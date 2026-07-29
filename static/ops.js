const $ = (id) => document.getElementById(id);
let cwTab = "elegiveis";
let liveCache = { chatwoot: null, waha: null, painel: null };
const UI_TICK_MS = 8000;
let tickLeft = UI_TICK_MS / 1000;
let refreshing = false;
const cardStore = new Map();
let cardSeq = 0;

function fmtNum(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("pt-BR").format(n);
}
function fmtUsd(n) {
  if (n == null) return "—";
  return `US$ ${Number(n).toFixed(4)}`;
}
function ago(iso) {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!t) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function card({
  tone = "",
  tag = "",
  title,
  href,
  sub = "",
  log = "",
  footLeft = "",
  footRight = "",
  footTone = "",
  detail = null,
}) {
  const id = `c${++cardSeq}`;
  cardStore.set(id, {
    source: detail?.source || tag || "Item",
    title: title || "—",
    tag: tag || "",
    tone: tone || "",
    href: href || "",
    sub: sub || "",
    log: log || "",
    footLeft: footLeft || "",
    footRight: footRight || "",
    fields: detail?.fields || [],
    raw: detail?.raw || null,
  });
  return `<article class="card ${tone}" data-card-id="${id}" role="button" tabindex="0">
    <div class="card-top"><span class="tag ${tone}">${esc(tag)}</span></div>
    <p class="card-title">${esc(title)}</p>
    ${sub ? `<p class="card-sub">${esc(sub)}</p>` : ""}
    ${log ? `<p class="card-log" title="${esc(log)}"><span class="log-label">Motivo</span>${esc(log)}</p>` : ""}
    <div class="card-foot"><span>${esc(footLeft)}</span><span class="prio ${footTone}">${esc(footRight)}</span></div>
  </article>`;
}

function openDrawer(id) {
  const d = cardStore.get(id);
  if (!d) return;
  const drawer = $("drawer");
  const backdrop = $("drawerBackdrop");
  $("drawerEyebrow").textContent = d.source || "Detalhe";
  $("drawerTitle").textContent = d.title || "—";

  const fields = [...(d.fields || [])];
  if (d.sub) fields.unshift({ label: "Resumo", value: d.sub });
  if (d.tag) fields.unshift({ label: "Tipo", value: d.tag });
  if (d.footLeft) fields.push({ label: "Contexto", value: d.footLeft });
  if (d.footRight) fields.push({ label: "Status", value: d.footRight });

  const kv = fields
    .filter((f) => f && f.value != null && String(f.value).trim() !== "")
    .map(
      (f) =>
        `<div class="detail-kv"><span>${esc(f.label)}</span><strong>${esc(String(f.value))}</strong></div>`
    )
    .join("");

  const logBlock = d.log
    ? `<div class="detail-block"><h3>Motivo / log</h3><p>${esc(d.log)}</p></div>`
    : `<div class="detail-block"><h3>Motivo / log</h3><p>Sem motivo registrado neste item.</p></div>`;

  const rawBlock = d.raw
    ? `<div class="detail-block"><h3>Payload</h3><p>${esc(
        typeof d.raw === "string" ? d.raw : JSON.stringify(d.raw, null, 2)
      )}</p></div>`
    : "";

  $("drawerBody").innerHTML = `${logBlock}${kv ? `<div class="detail-grid">${kv}</div>` : ""}${rawBlock}`;
  $("drawerFooter").innerHTML = d.href
    ? `<a class="btn primary" href="${esc(d.href)}" target="_blank" rel="noopener">Abrir no Chatwoot</a>
       <button type="button" class="btn ghost" id="drawerClose2">Fechar</button>`
    : `<button type="button" class="btn ghost" id="drawerClose2">Fechar</button>`;

  drawer.hidden = false;
  backdrop.hidden = false;
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  $("drawerClose2")?.addEventListener("click", closeDrawer, { once: true });
}

function closeDrawer() {
  const drawer = $("drawer");
  const backdrop = $("drawerBackdrop");
  drawer.classList.remove("is-open");
  drawer.hidden = true;
  backdrop.hidden = true;
  drawer.setAttribute("aria-hidden", "true");
}

function onCardActivate(e) {
  const el = e.target.closest("[data-card-id]");
  if (!el) return;
  if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
  if (e.type === "keydown") e.preventDefault();
  openDrawer(el.dataset.cardId);
}

function addBubble(role, text) {
  const log = $("chatLog");
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.innerHTML = `<span class="who">${role === "user" ? "Você" : "Monitor"}</span>`;
  const body = document.createElement("div");
  body.textContent = text;
  div.appendChild(body);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function setLive(ok, label, sub) {
  $("liveLabel").textContent = label;
  $("liveSub").textContent = sub;
  const dot = $("pulseDot");
  dot.classList.remove("on", "warn", "off");
  if (ok === true) dot.classList.add("on");
  else if (ok === "warn") dot.classList.add("warn");
  else dot.classList.add("off");
}

function renderFontes(fontes) {
  const map = [
    ["gestao", "Gestão"],
    ["painel", "Hub"],
    ["chatwoot", "Chatwoot"],
    ["waha", "WAHA"],
    ["lab", "Lab"],
    ["whatsapp", "WhatsApp"],
    ["reprocess_auto", "Reprocess"],
  ];
  $("fontes").innerHTML = map
    .map(([k, label]) => {
      const on = !!fontes?.[k];
      return `<span class="chip ${on ? "on" : ""}"><i class="d"></i>${label}</span>`;
    })
    .join("");
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || res.statusText || "erro");
  return data;
}

function renderChatwoot() {
  const cw = liveCache.chatwoot;
  if (!cw) {
    $("cwMeta").textContent = "Aguardando 1ª varredura…";
    $("cwList").innerHTML = `<div class="empty">Sem dados ainda. Use “Varrer Chatwoot”.</div>`;
    $("cwNEleg").textContent = "0";
    $("cwNPaus").textContent = "0";
    $("mCwFila").textContent = "—";
    return;
  }
  const tot = cw.totais || {};
  const nE = tot.elegiveis ?? (cw.elegiveis || []).length;
  const nP = tot.pausados_com_silencio ?? (cw.pausados || []).length;
  $("cwNEleg").textContent = nE;
  $("cwNPaus").textContent = nP;
  $("mCwFila").textContent = fmtNum(nE);
  $("mCwSub").textContent = `atualizado ${ago(cw.atualizado_em)}`;
  $("cwMeta").textContent = `Silêncio ≥ ${cw.silencio_minutos || 5} min · ${fmtNum(cw.conversas_analisadas)} analisadas · ${ago(cw.atualizado_em)}`;

  if (cwTab === "elegiveis") {
    const list = cw.elegiveis || [];
    $("cwList").innerHTML = list.length
      ? list
          .map((l) =>
            card({
              tone: "warn",
              tag: "Elegível",
              title: l.nome || l.telefone || "(sem nome)",
              href: l.link,
              sub: `${l.cliente || "—"} · inbox ${l.inbox_id}`,
              log: l.log || "",
              footLeft: `conv ${l.conversation_id}`,
              footRight: `${l.minutos_sem_resposta} min`,
              footTone: Number(l.minutos_sem_resposta) > 60 ? "bad" : "",
              detail: {
                source: "Chatwoot · elegível",
                fields: [
                  { label: "Cliente", value: l.cliente },
                  { label: "Telefone", value: l.telefone },
                  { label: "Account", value: l.account_id ?? l.account },
                  { label: "Inbox", value: l.inbox_id },
                  { label: "Conversa", value: l.conversation_id },
                  { label: "Silêncio", value: `${l.minutos_sem_resposta} min` },
                  { label: "Última msg", value: l.ultima_mensagem_em || l.last_activity_at },
                ],
                raw: l,
              },
            })
          )
          .join("")
      : `<div class="empty">Nenhum lead elegível agora.</div>`;
  } else if (cwTab === "pausados") {
    const list = cw.pausados || [];
    $("cwList").innerHTML = list.length
      ? list
          .map((l) =>
            card({
              tone: "violet",
              tag: "pausar_ia",
              title: l.nome || "(sem nome)",
              href: l.link,
              sub: l.cliente || "—",
              log: l.log || "",
              footLeft: `conv ${l.conversation_id}`,
              footRight: `${l.minutos_sem_resposta} min`,
              detail: {
                source: "Chatwoot · pausado",
                fields: [
                  { label: "Cliente", value: l.cliente },
                  { label: "Telefone", value: l.telefone },
                  { label: "Account", value: l.account_id ?? l.account },
                  { label: "Inbox", value: l.inbox_id },
                  { label: "Conversa", value: l.conversation_id },
                  { label: "Silêncio", value: `${l.minutos_sem_resposta} min` },
                  { label: "Label", value: "pausar_ia" },
                ],
                raw: l,
              },
            })
          )
          .join("")
      : `<div class="empty">Nenhum pausado com silêncio.</div>`;
  } else {
    const list = cw.por_conta || [];
    $("cwList").innerHTML = list.length
      ? list
          .map((c) =>
            card({
              tone: c.skipped ? "" : Number(c.elegiveis) > 0 ? "warn" : "ok",
              tag: c.skipped ? "Skip" : "Conta",
              title: `${c.account_nome} #${c.account_id}`,
              sub: `inboxes ${(c.inbox_ids || []).join("+") || "—"}`,
              log: c.log || c.erro || "",
              footLeft: `anal ${c.conversas_analisadas || 0}`,
              footRight: `${c.elegiveis || 0} eleg · ${c.pausados_com_silencio || 0} paus`,
              footTone: Number(c.elegiveis) > 0 ? "bad" : "",
              detail: {
                source: "Chatwoot · conta",
                fields: [
                  { label: "Account ID", value: c.account_id },
                  { label: "Nome", value: c.account_nome },
                  { label: "Inboxes", value: (c.inbox_ids || []).join(", ") },
                  { label: "Analisadas", value: c.conversas_analisadas },
                  { label: "Elegíveis", value: c.elegiveis },
                  { label: "Pausados", value: c.pausados_com_silencio },
                  { label: "Skipped", value: c.skipped ? "sim" : "não" },
                  { label: "Erro", value: c.erro },
                ],
                raw: c,
              },
            })
          )
          .join("")
      : `<div class="empty">Sem contas.</div>`;
  }
}

function renderWaha() {
  const w = liveCache.waha;
  if (!w) {
    $("wahaMeta").textContent = "Aguardando coleta…";
    $("wahaStats").innerHTML = "";
    $("wahaList").innerHTML = `<div class="empty">Sem dados WAHA.</div>`;
    $("mWahaRuin").textContent = "—";
    return;
  }
  const tot = w.totais || {};
  $("mWahaRuin").textContent = fmtNum(tot.ruins);
  $("mWahaSub").textContent = `${fmtNum(tot.working)} WORKING / ${fmtNum(tot.total)}`;
  $("wahaMeta").textContent = `Atualizado ${ago(w.atualizado_em)}`;
  $("wahaStats").innerHTML = `
    <span class="pill ok">WORKING ${fmtNum(tot.working)}</span>
    <span class="pill bad">ruins ${fmtNum(tot.ruins)}</span>
    <span class="pill">total ${fmtNum(tot.total)}</span>`;
  const ruins = w.ruins || [];
  $("wahaList").innerHTML = ruins.length
    ? ruins
        .map((s) =>
          card({
            tone: "bad",
            tag: "Atenção",
            title: s.name,
            sub: "Sessão fora de WORKING",
            log: s.log || `Status ${s.status}`,
            footLeft: "WAHA",
            footRight: s.status,
            footTone: "bad",
            detail: {
              source: "WAHA · sessão",
              fields: [
                { label: "Sessão", value: s.name },
                { label: "Status", value: s.status },
                { label: "Engine", value: s.engine },
                { label: "Me", value: s.me || s.pushName },
                { label: "Atualizado", value: s.atualizado_em || w.atualizado_em },
              ],
              raw: s,
            },
          })
        )
        .join("")
    : `<div class="empty">Todas as sessões WORKING.</div>`;
}

function renderHub() {
  const h = liveCache.painel;
  if (!h) {
    $("hubMeta").textContent = "Aguardando coleta…";
    $("hubStats").innerHTML = "";
    $("hubList").innerHTML = `<div class="empty">Sem dados do Hub.</div>`;
    return;
  }
  const saude = h.saudeGeral || "—";
  const cls = /ok|saudavel/i.test(saude) ? "ok" : /atencao/i.test(saude) ? "warn" : "bad";
  $("hubMeta").textContent = `Atualizado ${ago(h.atualizado_em)}`;
  $("hubStats").innerHTML = `
    <span class="pill ${cls}">saúde ${esc(saude)}</span>
    <span class="pill bad">serviços ${fmtNum((h.servicos_problema || []).length)}</span>
    <span class="pill warn">alertas ${fmtNum((h.alertas || []).length)}</span>`;

  const parts = [];
  for (const s of h.servicos_problema || []) {
    parts.push(
      card({
        tone: "bad",
        tag: s.tipo || "serviço",
        title: s.nome || "—",
        sub: `nível ${s.nivel || "—"}`,
        log: s.log || "",
        footLeft: "Hub",
        footRight: s.status || "problema",
        footTone: "bad",
        detail: {
          source: "Hub · serviço",
          fields: [
            { label: "Serviço", value: s.nome },
            { label: "Tipo", value: s.tipo },
            { label: "Nível", value: s.nivel },
            { label: "Status", value: s.status },
            { label: "Cliente", value: s.cliente },
            { label: "Atualizado", value: h.atualizado_em },
          ],
          raw: s,
        },
      })
    );
  }
  for (const a of h.alertas || []) {
    const texto = typeof a === "string" ? a : a.texto || JSON.stringify(a);
    const log = typeof a === "object" && a.log ? a.log : `Alerta do Hub: ${texto}`;
    parts.push(
      card({
        tone: "warn",
        tag: "Alerta",
        title: texto,
        log,
        footLeft: "Hub",
        footRight: "atenção",
        footTone: "",
        detail: {
          source: "Hub · alerta",
          fields: [
            { label: "Alerta", value: texto },
            { label: "Severidade", value: typeof a === "object" ? a.severidade || a.nivel : null },
            { label: "Atualizado", value: h.atualizado_em },
          ],
          raw: a,
        },
      })
    );
  }
  for (const c of h.clientes_problema || []) {
    const nome = typeof c === "string" ? c : c.nome || c.cliente || JSON.stringify(c);
    const log = typeof c === "object" && c.log ? c.log : `Cliente em problema no Hub: ${nome}`;
    parts.push(
      card({
        tone: "violet",
        tag: "Cliente",
        title: nome,
        log,
        footLeft: "parcial/offline",
        footRight: "revisar",
        detail: {
          source: "Hub · cliente",
          fields: [
            { label: "Cliente", value: nome },
            { label: "Status", value: typeof c === "object" ? c.status : null },
            { label: "Atualizado", value: h.atualizado_em },
          ],
          raw: c,
        },
      })
    );
  }
  $("hubList").innerHTML = parts.length ? parts.join("") : `<div class="empty">Nada crítico no Hub.</div>`;
}

function renderAllLive() {
  cardStore.clear();
  renderChatwoot();
  renderWaha();
  renderHub();
}

async function refresh({ forceLight = true } = {}) {
  if (refreshing) return;
  refreshing = true;
  const clock = $("liveClock");
  const clockText = $("liveClockText");
  if (clock) clock.classList.add("busy");
  if (clockText) clockText.textContent = "atualizando…";
  try {
    if (forceLight) {
      try {
        const light = await fetchJson("/ops/refresh-live", { method: "POST" });
        liveCache = {
          chatwoot: light.chatwoot ?? liveCache.chatwoot,
          waha: light.waha ?? liveCache.waha,
          painel: light.painel ?? liveCache.painel,
        };
      } catch (_) {
        /* cache antigo ainda serve */
      }
    }

    const [status, metrics, live] = await Promise.all([
      fetchJson("/ops/status"),
      fetchJson("/ops/metrics"),
      fetchJson("/ops/live"),
    ]);
    liveCache = {
      chatwoot: live.chatwoot ?? liveCache.chatwoot,
      waha: live.waha ?? liveCache.waha,
      painel: live.painel ?? liveCache.painel,
    };

    const operando = !!status.operando;
    const cwFila = liveCache.chatwoot?.totais?.elegiveis ?? 0;
    const ruins = liveCache.waha?.totais?.ruins ?? 0;
    const warn = ruins > 0 || cwFila > 0;
    setLive(
      operando ? (warn ? "warn" : true) : false,
      operando ? (warn ? "Atenção" : "Operando") : "Pausado",
      `${status.chatwoot?.contas_com_inbox || 0} contas IA · ${ago(status.uptime_desde)}`
    );
    renderFontes(status.fontes);
    $("schedInfo").textContent = (status.scheduler?.slots || []).join(", ") || "—";
    const u = status.ultimo_relatorio || {};
    $("ultimoInfo").textContent = u.salvo_em
      ? `Último relatório ${u.stamp || ""} · ${ago(u.salvo_em)}`
      : "Nenhum relatório ainda";
    $("chatEngine").textContent = status.fontes?.lab ? "Infinity Lab" : status.fontes?.openai_fallback ? "OpenAI" : "sem LLM";

    const llm = metrics.llm_hoje || {};
    const repro = metrics.reprocess_hoje || {};
    $("mTokens").textContent = fmtNum(llm.total_tokens);
    $("mTokensSub").textContent = `${fmtNum(llm.calls)} calls`;
    $("mCost").textContent = fmtUsd(llm.cost_usd);
    $("mCap").textContent = fmtNum(repro.capturados);
    $("mSent").textContent = fmtNum(repro.enviados);
    $("mSentSub").textContent = `stub ${fmtNum(repro.stub)} · err ${fmtNum(repro.erros)}`;
    $("diaLabel").textContent = metrics.dia || "—";

    renderAllLive();
  } catch (err) {
    setLive(false, "Offline", err.message || "falha");
    if (clockText) clockText.textContent = "offline";
  } finally {
    refreshing = false;
    if (clock) clock.classList.remove("busy");
    tickLeft = UI_TICK_MS / 1000;
    updateClockLabel();
  }
}

function updateClockLabel() {
  const el = $("liveClockText");
  if (!el || refreshing) return;
  const wahaAgo = liveCache.waha?.atualizado_em ? ago(liveCache.waha.atualizado_em) : "—";
  el.textContent = `ao vivo · ${tickLeft}s · WAHA ${wahaAgo}`;
}

function showLog(text) {
  const el = $("actionLog");
  el.hidden = false;
  el.textContent = text;
}

$("cwTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  cwTab = btn.dataset.tab;
  [...$("cwTabs").querySelectorAll(".seg-btn")].forEach((t) => t.classList.toggle("on", t === btn));
  renderAllLive();
});

["cwList", "wahaList", "hubList"].forEach((id) => {
  const el = $(id);
  el.addEventListener("click", onCardActivate);
  el.addEventListener("keydown", onCardActivate);
});
$("drawerClose").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("drawer").hidden) closeDrawer();
});

$("btnRefresh").addEventListener("click", () => refresh({ forceLight: true }));

$("btnRelatorio").addEventListener("click", async () => {
  const btn = $("btnRelatorio");
  btn.disabled = true;
  try {
    const data = await fetchJson("/relatorio/gerar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enviar: true, forcar: true }),
    });
    showLog(`Relatório ok · whatsapp=${data.enviado_whatsapp}`);
    await refresh();
  } catch (err) {
    showLog(`Erro: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
});

$("btnSilencio").addEventListener("click", async () => {
  const btn = $("btnSilencio");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Varrendo…";
  try {
    const data = await fetchJson("/chatwoot/leads-silencio");
    await refresh();
    showLog(`Varredura ${data.status} · elegíveis=${data.dados?.totais?.elegiveis ?? 0}`);
  } catch (err) {
    showLog(`Erro: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
});

$("chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("chatInput");
  const pergunta = input.value.trim();
  if (!pergunta) return;
  addBubble("user", pergunta);
  input.value = "";
  const send = $("chatSend");
  send.disabled = true;
  try {
    const data = await fetchJson("/perguntar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pergunta, thread_id: "ops-ui" }),
    });
    addBubble("bot", data.resposta || "(sem resposta)");
    await refresh();
  } catch (err) {
    addBubble("bot", `Falha: ${err.message}`);
  } finally {
    send.disabled = false;
    input.focus();
  }
});

addBubble("bot", "Monitor ao vivo: WAHA/Hub atualizam sozinhos ~15–20s. Chatwoot depende da varredura (poller ou botão).");
refresh({ forceLight: true });
setInterval(() => {
  tickLeft = Math.max(0, tickLeft - 1);
  updateClockLabel();
}, 1000);
setInterval(() => refresh({ forceLight: true }), UI_TICK_MS);

// evita aba em background martelar API sem necessidade extrema — ainda atualiza, mas ok
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh({ forceLight: true });
});
