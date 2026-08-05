const $ = (id) => document.getElementById(id);
let cwTab = "elegiveis";
let reproTab = "eventos";
let liveCache = { chatwoot: null, painel: null };
let reproCache = null;
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
    queueId: detail?.queueId || null,
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

  const actions = [];
  if (d.queueId) {
    actions.push(
      `<button type="button" class="btn primary" id="drawerQueueBtn">Consultar fila Francisco</button>`
    );
  }
  if (d.href) {
    actions.push(
      `<a class="btn primary" href="${esc(d.href)}" target="_blank" rel="noopener">Abrir no Chatwoot</a>`
    );
  }
  actions.push(`<button type="button" class="btn ghost" id="drawerClose2">Fechar</button>`);
  $("drawerFooter").innerHTML = actions.join("");

  drawer.hidden = false;
  backdrop.hidden = false;
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  $("drawerClose2")?.addEventListener("click", closeDrawer, { once: true });
  $("drawerQueueBtn")?.addEventListener(
    "click",
    () => {
      closeDrawer();
      if ($("reproQueueInput")) $("reproQueueInput").value = d.queueId;
      consultarQueueStatus(d.queueId);
      $("panelRepro")?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    { once: true }
  );
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

async function fetchJson(url, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? 12000;
  const { timeoutMs: _drop, ...rest } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...rest, signal: ctrl.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || data.mensagem || res.statusText || "erro");
    return data;
  } catch (err) {
    if (err?.name === "AbortError") throw new Error(`timeout ${timeoutMs}ms em ${url}`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
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

function isWahaNoise(text) {
  const t = String(text || "").toLowerCase();
  return t.includes("waha") || t.includes("números (waha)") || t.includes("numeros (waha)");
}

function renderHub() {
  const h = liveCache.painel;
  if (!h) {
    $("hubMeta").textContent = "Aguardando coleta…";
    $("hubStats").innerHTML = "";
    $("hubList").innerHTML = `<div class="empty">Sem dados do Hub.</div>`;
    if ($("mHubSaude")) $("mHubSaude").textContent = "—";
    return;
  }
  const saude = h.saudeGeral || "—";
  const cls = /ok|saudavel/i.test(saude) ? "ok" : /atencao/i.test(saude) ? "warn" : "bad";
  if ($("mHubSaude")) {
    $("mHubSaude").textContent = saude;
    $("mHubSub").textContent = `atualizado ${ago(h.atualizado_em)}`;
  }
  $("hubMeta").textContent = `Atualizado ${ago(h.atualizado_em)}`;

  const servicos = (h.servicos_problema || []).filter(
    (s) => !isWahaNoise(s.nome) && !isWahaNoise(s.tipo) && !isWahaNoise(s.log)
  );
  const alertas = (h.alertas || []).filter((a) => {
    const texto = typeof a === "string" ? a : a.texto || a.log || JSON.stringify(a);
    return !isWahaNoise(texto);
  });

  $("hubStats").innerHTML = `
    <span class="pill ${cls}">saúde ${esc(saude)}</span>
    <span class="pill bad">serviços ${fmtNum(servicos.length)}</span>
    <span class="pill warn">alertas ${fmtNum(alertas.length)}</span>`;

  const parts = [];
  for (const s of servicos) {
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
  for (const a of alertas) {
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
  renderHub();
  renderReprocess();
}

function reproTone(status) {
  const s = String(status || "").toLowerCase();
  if (["ok", "success", "enviado", "enfileirado", "ativo"].includes(s)) return "ok";
  if (["stub", "dedup", "pending", "running", "sem_token", "desligado"].includes(s)) return "warn";
  if (["erro", "error", "canceled", "ignorado"].includes(s)) return s === "ignorado" ? "violet" : "bad";
  return "";
}

function renderReprocess() {
  const panel = $("panelRepro");
  if (!panel) return;
  const data = reproCache;
  if (!data) {
    $("reproMeta").textContent = "Carregando…";
    $("reproList").innerHTML = `<div class="empty">Aguardando dados do reprocessamento.</div>`;
    return;
  }

  const cfg = data.config || {};
  const hoje = data.hoje || {};
  const health = data.health || {};
  const modo = data.modo || "desligado";
  const modoLabel =
    modo === "ativo"
      ? "AUTO ativo"
      : modo === "sem_token"
        ? "Sem token"
        : modo === "token_invalido"
          ? "Token inválido"
          : modo === "api_indisponivel"
            ? "API fora"
            : "Desligado (stub)";
  const chip = $("reproModeChip");
  chip.className = `chip ${
    modo === "ativo" ? "on" : modo === "sem_token" || modo === "token_invalido" || modo === "api_indisponivel" ? "warn" : "bad"
  }`;
  $("reproModeLabel").textContent = modoLabel;

  const healthTxt = health.ok ? "API ok" : health.erro ? `API: ${health.erro}` : `API HTTP ${health.http_status || "—"}`;
  const auth = data.auth_probe || {};
  const authTxt = auth.unauthorized
    ? "auth 401 (token rejeitado)"
    : auth.ok
      ? "auth ok"
      : auth.erro
        ? `auth: ${auth.erro}`
        : auth.http_status
          ? `auth HTTP ${auth.http_status}`
          : "auth —";
  $("reproMeta").textContent =
    `${cfg.endpoint || "—"} · lote ≤${cfg.max_batch || 20} · poll ${cfg.poll_seconds || "—"}s · ${healthTxt} · ${authTxt}`;

  const elegAgora = liveCache.chatwoot?.totais?.elegiveis ?? "—";
  $("reproStats").innerHTML = [
    ["Capturados", hoje.capturados],
    ["Enviados", hoje.enviados],
    ["Stub", hoje.stub],
    ["Erros", hoje.erros],
    ["Elegíveis agora", elegAgora],
  ]
    .map(
      ([label, val]) =>
        `<div class="repro-stat"><span>${esc(label)}</span><strong>${esc(fmtNum(val))}</strong></div>`
    )
    .join("");

  if (reproTab === "eventos") {
    const list = data.eventos || [];
    $("reproList").innerHTML = list.length
      ? list
          .map((ev) =>
            card({
              tone: reproTone(ev.status || ev.kind),
              tag: ev.kind || "evento",
              title: `${ev.status || "—"} · ${ev.count ?? 0} lead(s)`,
              sub: ev.detail || "",
              footLeft: ago(ev.ts),
              footRight: ev.ts ? String(ev.ts).slice(11, 19) : "",
              detail: {
                source: "Reprocess · evento",
                fields: [
                  { label: "Kind", value: ev.kind },
                  { label: "Status", value: ev.status },
                  { label: "Count", value: ev.count },
                  { label: "Quando", value: ev.ts },
                  { label: "Detalhe", value: ev.detail },
                ],
                raw: ev,
              },
            })
          )
          .join("")
      : `<div class="empty">Nenhum evento ainda. Use “Reprocessar agora” ou aguarde o poller.</div>`;
  } else if (reproTab === "enviados") {
    const list = data.enviados || [];
    $("reproList").innerHTML = list.length
      ? list
          .map((item) =>
            card({
              tone: reproTone(item.status),
              tag: item.status || "enviado",
              title: `conv ${item.conversation_id || "—"} · conta ${item.account_id || "—"}`,
              sub: item.queue_id ? `queue ${item.queue_id}` : item.detail || "sem queue_id",
              log: item.detail || "",
              footLeft: ago(item.ts),
              footRight: item.queue_id ? "consultar" : "—",
              detail: {
                source: "Reprocess · enfileirado",
                fields: [
                  { label: "Account", value: item.account_id },
                  { label: "Conversa", value: item.conversation_id },
                  { label: "Queue ID", value: item.queue_id },
                  { label: "Status local", value: item.status },
                  { label: "Key", value: item.key },
                  { label: "Quando", value: item.ts },
                ],
                raw: item,
                queueId: item.queue_id || null,
              },
            })
          )
          .join("")
      : `<div class="empty">Nada enfileirado ainda hoje.</div>`;
  } else {
    const lote = data.ultimo_lote;
    if (!lote) {
      $("reproList").innerHTML = `<div class="empty">Nenhum lote enviado ainda.</div>`;
    } else {
      const resultados = lote.resultados || [];
      const head = card({
        tone: reproTone(lote.status),
        tag: "lote",
        title: `status ${lote.status || "—"} · HTTP ${lote.http_status ?? "—"}`,
        sub: `aceitos ${lote.aceitos ?? 0} · ignorados ${lote.ignorados ?? 0} · erros ${lote.erros ?? 0} · lotes ${lote.lotes ?? 1}`,
        footLeft: ago(lote.ts),
        footRight: lote.endpoint || "",
        detail: {
          source: "Reprocess · último lote",
          fields: [
            { label: "Status", value: lote.status },
            { label: "HTTP", value: lote.http_status },
            { label: "Endpoint", value: lote.endpoint },
            { label: "Detalhe", value: lote.detalhe },
            { label: "Queue IDs", value: (lote.queue_ids || []).join(", ") },
          ],
          raw: lote,
        },
      });
      const items = resultados.length
        ? resultados
            .map((r) =>
              card({
                tone: reproTone(r.status),
                tag: r.status || "item",
                title: `conv ${r.conversation_id ?? "—"}`,
                sub: r.queue_id
                  ? `queue ${r.queue_id}`
                  : r.mensagem || r.motivo || "",
                log: r.motivo || r.mensagem || "",
                footLeft: r.idempotency_key ? String(r.idempotency_key).slice(0, 18) + "…" : "",
                footRight: r.motivo || r.status || "",
                detail: {
                  source: "Reprocess · item do lote",
                  fields: [
                    { label: "Conversa", value: r.conversation_id },
                    { label: "Status", value: r.status },
                    { label: "Motivo", value: r.motivo },
                    { label: "Mensagem", value: r.mensagem },
                    { label: "Queue ID", value: r.queue_id },
                    { label: "Idempotency", value: r.idempotency_key },
                  ],
                  raw: r,
                  queueId: r.queue_id || null,
                },
              })
            )
            .join("")
        : `<div class="empty">Lote sem array resultados (stub/dedup/erro cedo).</div>`;
      $("reproList").innerHTML = head + items;
    }
  }
}

async function loadReprocess() {
  try {
    reproCache = await fetchJson("/ops/reprocess?light=1", { timeoutMs: 8000 });
    renderReprocess();
  } catch (err) {
    if ($("reproMeta")) $("reproMeta").textContent = `Falha ao carregar: ${err.message}`;
  }
}

async function consultarQueueStatus(id) {
  const raw = String(id || "").trim();
  if (!raw) return;
  const log = $("reproStatusLog");
  log.hidden = false;
  log.textContent = `Consultando ${raw}…`;
  try {
    const looksUuid = /^[0-9a-f]{8}-/i.test(raw);
    const q = looksUuid ? `request_id=${encodeURIComponent(raw)}` : `queue_id=${encodeURIComponent(raw)}`;
    const data = await fetchJson(`/chatwoot/reprocessar/status?${q}`, { timeoutMs: 20000 });
    log.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    log.textContent = `Erro: ${err.message}`;
  }
}


async function refresh({ forceLight = true } = {}) {
  if (refreshing) return;
  refreshing = true;
  const clock = $("liveClock");
  const clockText = $("liveClockText");
  if (clock) clock.classList.add("busy");
  if (clockText) clockText.textContent = "atualizando…";
  try {
    // refresh-live pode demorar — não bloqueia o restante da UI
    if (forceLight) {
      fetchJson("/ops/refresh-live", { method: "POST", timeoutMs: 6000 })
        .then((light) => {
          liveCache = {
            chatwoot: light.chatwoot ?? liveCache.chatwoot,
            painel: light.painel ?? liveCache.painel,
          };
          renderAllLive();
        })
        .catch(() => {});
    }

    const [status, metrics, live] = await Promise.all([
      fetchJson("/ops/status", { timeoutMs: 8000 }),
      fetchJson("/ops/metrics", { timeoutMs: 8000 }),
      fetchJson("/ops/live", { timeoutMs: 8000 }),
    ]);
    liveCache = {
      chatwoot: live.chatwoot ?? liveCache.chatwoot,
      painel: live.painel ?? liveCache.painel,
    };

    const operando = !!status.operando;
    const cwFila = liveCache.chatwoot?.totais?.elegiveis ?? 0;
    const hubWarn = /atencao|crit/i.test(String(liveCache.painel?.saudeGeral || ""));
    const warn = hubWarn || cwFila > 0;
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
    // KPI principal = elegíveis AGORA (lista viva), não a soma histórica de ticks
    $("mCap").textContent = fmtNum(cwFila);
    $("mSent").textContent = fmtNum(repro.enviados);
    $("mSentSub").textContent =
      `únicos dia ${fmtNum(repro.capturados)} · err ${fmtNum(repro.erros)}`;
    $("diaLabel").textContent = metrics.dia || "—";

    if (!reproCache) {
      reproCache = {
        modo: status.fontes?.reprocess_auto ? "ativo" : "desligado",
        config: {},
        hoje: repro,
        eventos: metrics.reprocess_recentes || [],
        enviados: metrics.reprocess_enviados || [],
        ultimo_lote: metrics.reprocess_ultimo_lote || null,
        health: null,
      };
    }

    renderAllLive();
    loadReprocess();
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
  const hubAgo = liveCache.painel?.atualizado_em ? ago(liveCache.painel.atualizado_em) : "—";
  el.textContent = `ao vivo · ${tickLeft}s · Hub ${hubAgo}`;
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

$("reproTabs")?.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  reproTab = btn.dataset.tab;
  [...$("reproTabs").querySelectorAll(".seg-btn")].forEach((t) => t.classList.toggle("on", t === btn));
  renderReprocess();
});

["cwList", "hubList", "reproList"].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("click", onCardActivate);
  el.addEventListener("keydown", onCardActivate);
});
$("drawerClose").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("drawer").hidden) closeDrawer();
});

$("btnRefresh").addEventListener("click", () => refresh({ forceLight: true }));
$("btnReproRefresh")?.addEventListener("click", () => loadReprocess());

$("reproLookupForm")?.addEventListener("submit", (e) => {
  e.preventDefault();
  consultarQueueStatus($("reproQueueInput").value);
});

$("btnReproForce")?.addEventListener("click", async () => {
  const btn = $("btnReproForce");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Forçando…";
  try {
    const data = await fetchJson("/chatwoot/reprocessar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enviar: true, force: true }),
      timeoutMs: 300000,
    });
    const r = data.reprocessamento || {};
    showLog(
      `Força ${r.status || "—"} · aceitos=${r.aceitos ?? "—"} · ` +
        `ignorados=${r.ignorados ?? "—"} · queue_ids=${(r.queue_ids || []).length}`
    );
    reproTab = "lote";
    [...$("reproTabs").querySelectorAll(".seg-btn")].forEach((t) =>
      t.classList.toggle("on", t.dataset.tab === "lote")
    );
    await loadReprocess();
    await refresh();
  } catch (err) {
    showLog(`Erro força: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
});

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

$("btnReprocess").addEventListener("click", async () => {
  const btn = $("btnReprocess");
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "Enviando…";
  showLog("Reprocessando: varrendo Chatwoot e enviando ao Francisco… (pode levar 1–2 min)");
  try {
    const data = await fetchJson("/chatwoot/reprocessar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enviar: true, force: false }),
      timeoutMs: 300000,
    });
    await refresh();
    const r = data.reprocessamento || {};
    const auto = data.automatico_habilitado ? "AUTO on" : "AUTO off (stub)";
    const resumoItens = (r.resultados || [])
      .slice(0, 5)
      .map((x) => `${x.conversation_id}:${x.status}${x.motivo ? "(" + x.motivo + ")" : ""}`)
      .join(", ");
    showLog(
      `Reprocess ${r.status || "—"} · ${auto} · ` +
        `elegíveis=${(data.elegiveis || []).length} · ` +
        `enviados=${r.enviados ?? 0} · aceitos=${r.aceitos ?? "—"} · ` +
        `ignorados=${r.ignorados ?? "—"} · erros=${r.erros ?? "—"} · ` +
        `http=${r.http_status ?? "—"} · ` +
        `detalhe=${r.detalhe || "—"}` +
        (resumoItens ? ` · itens=[${resumoItens}]` : "")
    );
    reproTab = "lote";
    [...($("reproTabs")?.querySelectorAll(".seg-btn") || [])].forEach((t) =>
      t.classList.toggle("on", t.dataset.tab === "lote")
    );
    await loadReprocess();
  } catch (err) {
    showLog(`Erro reprocess: ${err.message}`);
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

addBubble("bot", "Monitor ao vivo: Hub atualiza sozinho ~15–20s. Chatwoot depende da varredura (poller ou botão).");
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
