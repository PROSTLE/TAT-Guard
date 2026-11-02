// The shell: sign-in, header, the numbers strip, the Exasol rail, routing, and the one poll every page shares.
import { api, h, clear, n, rs, secs, when, toast, plural, markPath } from "./common.js";
import { livePage } from "./page-live.js";
import { casesPage } from "./page-cases.js";
import { askPage } from "./page-ask.js";
import { proofPage } from "./page-proof.js";

const PAGES = { live: livePage, cases: casesPage, ask: askPage, proof: proofPage };
const NAV = [["live", "Live"], ["cases", "Cases"], ["ask", "Ask"], ["proof", "Proof"]];

export const ctx = { session: null, meta: null, poll: null, go: (page) => { location.hash = `#/${page}`; } };

const root = document.getElementById("app");
let current = null;
let currentName = null;
let els = null;
let seq = 0;
let pollTimer = null;
const lastStats = {};

function parseHash() {
  const [page, qs] = location.hash.replace(/^#\/?/, "").split("?");
  return { page: PAGES[page] ? page : "live", params: Object.fromEntries(new URLSearchParams(qs || "")) };
}

// ---------------------------------------------------------------- sign in
function gate(error) {
  const input = h("input", { type: "password", id: "code", autocomplete: "off", required: true, placeholder: "From your invitation" });
  const err = h("div.gate-err", { role: "alert" }, error || "");
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      try {
        await signIn(input.value.trim());
      } catch (ex) {
        err.textContent = ex.message;
      }
    },
  }, h("label.f", {}, h("span", "Access code"), input), err, h("button.btn.primary.wide", { type: "submit" }, "Open the demo"));
  clear(root, h("div.gate", {}, h("div.gate-card", {},
    h("h1", "TAT Guard"),
    h("p", "Make a UPI payment fail and watch Exasol catch it."),
    form,
    h("p.gate-foot", "All data is synthetic. No real bank, account or payment is involved."))));
  input.focus();
}

async function signIn(code) {
  ctx.session = await api("/api/session", { code, role: "analyst" });
  history.replaceState(null, "", location.pathname + location.hash);
  await start();
}

// ---------------------------------------------------------------- shell
function persona(role) {
  const p = ctx.session.personas[role];
  return h("button", {
    "aria-pressed": String(ctx.session.persona.role === role), title: p.title,
    onclick: async () => {
      ctx.session = await api("/api/session", { role });
      renderPersonas();
      current?.onPersona?.();
      toast(`You are now ${p.name}, ${p.title.toLowerCase()}.`);
    },
  }, p.name);
}

function renderPersonas() {
  clear(els.personas, persona("analyst"), persona("approver"));
}

function shell() {
  els = {
    nav: h("nav.nav", { "aria-label": "Main" }),
    date: h("b.num", "–"),
    personas: h("div.seg", { role: "group", "aria-label": "Acting as" }),
    strip: h("div.strip"),
    main: h("main", { id: "main" }),
    feed: h("div.feed", { "aria-live": "off" }, h("div.rail-empty", "Every statement this demo runs on Exasol appears here, with its real time and row count. Click one to read the SQL.")),
    dot: h("span.dot"),
    version: h("small", ""),
    sub: h("div.rail-sub", "Connecting to Exasol"),
  };
  els.moveDay = h("button.btn.small", {
    title: "Move the bank's date forward. Every penalty recalculates at once.",
    onclick: () => moveClock(1),
  }, "+1 day");
  clear(root, h("div.shell", {},
    h("header.top", {},
      h("div.brand", {}, "TAT Guard", h("small", "every stuck rupee, on a clock")),
      els.nav,
      h("div.top-right", {},
        h("span.tag.synthetic", { title: "Visitors create the failures, but no real bank, account or payment is involved." }, "Synthetic data"),
        h("div.bankdate", {}, h("span", "Bank date"), els.date, els.moveDay),
        els.personas)),
    els.strip,
    els.main,
    h("aside.rail", { "aria-label": "Exasol activity" },
      h("div.rail-head", {}, els.dot, "Exasol, live", els.version),
      els.sub,
      els.feed)));
  renderPersonas();
}

export async function moveClock(days) {
  try {
    await api("/api/live/clock", { days });
    markPath("clock");
    ctx.pendingClock = true;
    tick();
  } catch (e) {
    toast(e.message, true);
  }
}

function renderNav(page, pending) {
  clear(els.nav, NAV.map(([key, label]) => h("a", {
    href: `#/${key}`, "aria-current": key === page ? "page" : null,
  }, label, key === "cases" && Number(pending) > 0 ? h("span.count.alert", { title: "Waiting for approval" }, pending) : null)));
}

function stat(key, value, label, cls) {
  const changed = lastStats[key] !== undefined && lastStats[key] !== value;
  lastStats[key] = value;
  return h(`div.stat${cls ? "." + cls : ""}${changed ? ".changed" : ""}`, {}, h("b", value), h("small", label));
}

function renderStrip(k, lastRun) {
  const ms = lastRun?.total_ms ?? k.LAST_RECON_MS;
  clear(els.strip,
    stat("added", rs(k.NEW_ACCRUAL_RS), "added tomorrow if nothing changes", "hot"),
    stat("accruing", n(k.ACCRUING_N), "cases on the clock"),
    stat("stuck", rs(k.STUCK_RS), "customer money stuck"),
    stat("txns", n(k.TXNS), "payments in Exasol"),
    stat("recon", secs(ms), "last full reconciliation"));
}

// ---------------------------------------------------------------- rail
function planTable(plan) {
  return [h("p.plan-note", "How Exasol ran it (from its own profile):"), h("table.plan", {},
    h("thead", {}, h("tr", {}, h("th", "Step"), h("th", "Object"), h("th.r", "Rows in"), h("th.r", "Rows out"), h("th.r", "Time"))),
    h("tbody", {}, plan.map((p) => h("tr", {},
      h("td", p.part), h("td", p.object || ""), h("td.r", p.rows_in === null ? "" : n(p.rows_in)),
      h("td.r", p.rows_out === null ? "" : n(p.rows_out)), h("td.r", p.ms === null ? "" : `${n(p.ms)} ms`)))))];
}

function eventRow(e) {
  const meta = [e.ms !== null && e.ms !== undefined ? secs(e.ms) : null, e.rows !== null && e.rows !== undefined ? plural(e.rows, "row") : null].filter(Boolean).join(" · ");
  const detail = (e.sql || e.plan?.length) ? h("div.ev-detail.hidden", {}, e.sql ? h("pre", e.sql) : null, e.plan?.length ? planTable(e.plan) : null) : null;
  const row = h(`div.ev${e.tone ? "." + e.tone : ""}`, {
    "data-seq": e.seq,
    onclick: (ev) => {
      if (!detail || ev.target.closest(".ev-detail")) return;
      detail.classList.toggle("hidden");
      row.classList.toggle("open");
    },
  },
  h("div.ev-top", {}, h(`span.ev-actor.${e.actor.split(" ")[0]}`, e.actor), e.at),
  h("div.ev-title", e.title),
  meta ? h("div.ev-meta", meta) : null,
  detail);
  return row;
}

function pushEvents(events) {
  if (!events.length) return;
  els.feed.querySelector(".rail-empty")?.remove();
  for (const e of events) {
    const row = eventRow(e);
    const old = e.replaces && els.feed.querySelector(`[data-seq="${e.replaces}"]`);
    if (old) old.replaceWith(row);
    else els.feed.prepend(row);
  }
  while (els.feed.children.length > 140) els.feed.lastChild.remove();
}

// ---------------------------------------------------------------- poll
async function tick() {
  clearTimeout(pollTimer);
  let busy = false;
  try {
    const st = await api(`/api/live/state?since=${seq}`);
    if (st.seq < seq) { seq = 0; clear(els.feed); }
    seq = st.seq;
    ctx.poll = st;
    busy = Boolean(st.run) || Boolean(st.working) || st.queued > 0;
    pushEvents(st.events);
    els.date.textContent = when(st.kpi.AS_OF);
    els.dot.className = `dot ${busy ? "busy" : "on"}`;
    els.sub.textContent = st.run?.title || st.working || (st.queued ? `${plural(st.queued, "job")} waiting` : "Idle. Waiting for something to do.");
    renderStrip(st.kpi, st.last_run);
    renderNav(parseHash().page, st.kpi.PENDING);
    if (ctx.pendingClock) {
      const job = [...st.mine].reverse().find((j) => j.kind === "clock");
      if (job?.state === "done") {
        ctx.pendingClock = false;
        toast(`Added tomorrow went from ${rs(job.before.added_tomorrow)} to ${rs(job.after.added_tomorrow)}. Exasol recomputed every case in ${secs(job.recompute_ms)}.`);
      } else if (job?.state === "failed") {
        ctx.pendingClock = false;
        toast(job.error, true);
      }
    }
    current?.onPoll?.(st);
  } catch (e) {
    if (e.status === 401) { seq = 0; ctx.session = null; return boot(); }
    els.dot.className = "dot";
    els.sub.textContent = "Cannot reach the server. Retrying.";
  }
  pollTimer = setTimeout(tick, busy ? 500 : 1500);
}

function route() {
  const { page, params } = parseHash();
  if (page !== currentName) {
    current?.unmount?.();
    currentName = page;
    clear(els.main);
    current = PAGES[page](els.main, params);
  } else {
    current?.onParams?.(params);
  }
  if (ctx.poll) renderNav(page, ctx.poll.kpi.PENDING);
  else renderNav(page, 0);
}

async function start() {
  ctx.meta = await api("/api/meta");
  shell();
  route();
  tick();
  api("/api/health").then((x) => { els.version.textContent = x.version ? `v${x.version}` : ""; }).catch(() => {});
}

async function boot() {
  try {
    ctx.session = await api("/api/session");
  } catch (e) {
    return clear(root, h("div.gate", {}, h("div.gate-card", {}, h("h1", "TAT Guard"), h("p", `The server did not answer: ${e.message}`))));
  }
  if (ctx.session.authenticated) return start();
  const code = new URLSearchParams(location.search).get("code");
  if (code) {
    try { return await signIn(code); } catch (e) { return gate(e.message); }
  }
  gate();
}

window.addEventListener("hashchange", () => { if (els) route(); });
boot();
