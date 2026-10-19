/* TAT Guard single-page UI. Every figure shown is read from the JSON API (ui/api.py -> Exasol); nothing here
   invents a number. Labels and colours below are presentation only. All text from the database is escaped. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icons = (root) => window.lucide && window.lucide.createIcons({ root: root || document });
  const IN = new Intl.NumberFormat("en-IN");
  const IN2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const isNum = v => v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
  const fmt = {
    n: v => isNum(v) ? IN.format(Number(v)) : "–",
    rs: v => {
      if (!isNum(v)) return "–";
      const x = Number(v);
      return "₹" + (Number.isInteger(x) ? IN.format(x) : IN2.format(x));
    },
    rsShort: v => {          // axis labels only
      const x = Number(v);
      if (Math.abs(x) >= 1e7) return "₹" + (x / 1e7).toFixed(1).replace(/\.0$/, "") + " Cr";
      if (Math.abs(x) >= 1e5) return "₹" + (x / 1e5).toFixed(1).replace(/\.0$/, "") + " L";
      if (Math.abs(x) >= 1e3) return "₹" + (x / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
      return "₹" + IN.format(x);
    },
    pct: v => isNum(v) ? `${v}%` : "–",
    day: iso => {
      if (!iso) return "–";
      const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
      return Number.isNaN(d.getTime()) ? esc(iso) : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    },
    dayLong: iso => {
      if (!iso) return "–";
      const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
      return Number.isNaN(d.getTime()) ? esc(iso) : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    },
    dt: s => {
      if (!s) return "–";
      const d = new Date(String(s).replace(" ", "T"));
      return Number.isNaN(d.getTime()) ? esc(s) : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
    },
    ago: s => {
      const d = new Date(String(s).replace(" ", "T"));
      if (Number.isNaN(d.getTime())) return esc(s);
      const sec = Math.round((Date.now() - d.getTime()) / 1000);
      if (sec < 60) return "just now";
      if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
      if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
      return fmt.dt(s);
    },
  };
  const title = s => String(s || "").toLowerCase().replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase());

  async function call(path, body) {
    const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error */ }
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function toast(msg, bad = false) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.innerHTML = `<i data-lucide="${bad ? "circle-alert" : "circle-check"}"></i><div>${msg}</div>`;
    $("#toasts").appendChild(el);
    icons(el);
    setTimeout(() => el.remove(), bad ? 9000 : 6000);
  }

  // ------------------------------------------------------------------ presentation metadata (labels and colours only)
  // Which states, sorts, page sizes, action types and statuses exist comes from /api/meta (state.meta); the maps
  // below only name and colour them, with a fallback for any value they do not know (tests/test_ui_contract.py).
  const CLASS_META = {
    DEBIT_NO_CREDIT: { label: "Debit, no credit", color: "#B42318" },
    LATE_FILE: { label: "Late settlement file", color: "#E29A3B" },
    AMOUNT_MISMATCH: { label: "Amount mismatch", color: "#1D4F91" },
    NPCI_SUCCESS_NO_CBS: { label: "NPCI success, no CBS debit", color: "#5B3FB8" },
    DUPLICATE_POSTING: { label: "Duplicate posting", color: "#0F6B5C" },
    NPCI_MISSING: { label: "Missing in NPCI", color: "#667085" },
    UNMATCHED_CBS_DEBIT: { label: "Unmatched CBS debit", color: "#98A2B3" },
  };
  const classMeta = c => CLASS_META[c] || { label: title(c), color: "#98A2B3" };
  const STATE_META = {
    OVERDUE: { label: "Overdue", tone: "danger" }, AT_RISK: { label: "At risk", tone: "warn" },
    WITHIN_TAT: { label: "Within TAT", tone: "info" }, COMPENSATION_DUE: { label: "Compensation due", tone: "violet" },
    NO_TAT_CLOCK: { label: "No TAT clock", tone: "neutral" },
  };
  const ACTION_META = {
    POST_REVERSAL: { label: "Post reversal", icon: "undo-2", cta: "Propose reversal" },
    PAY_COMPENSATION: { label: "Pay compensation", icon: "hand-coins", cta: "Propose compensation" },
    CHASE_SETTLEMENT_FILE: { label: "Chase settlement file", icon: "file-clock", cta: "Propose file chase" },
  };
  const actionMeta = a => ACTION_META[a] || { label: title(a), icon: "clipboard-check", cta: "Propose " + title(a).toLowerCase() };
  const STATUS_TONE = { PROPOSED: "warn", APPROVED: "info", EXECUTED: "brand", LOGGED: "brand", REJECTED: "neutral", FAILED: "danger" };
  const STATUS_TAB = { PROPOSED: "Waiting for approval" };
  const SORT_LABEL = { rank: "priority", owed: "owed tomorrow", amount: "amount", time: "most recent", deadline: "earliest deadline" };
  const pill = (text, tone) => `<span class="pill ${tone}">${esc(text)}</span>`;
  const statePill = s => s ? pill((STATE_META[s] || { label: title(s) }).label, (STATE_META[s] || { tone: "neutral" }).tone) : "";
  const classTag = c => `<span class="cls"><i style="background:${classMeta(c).color}"></i>${esc(classMeta(c).label)}</span>`;
  const sizeOptions = (cur) => state.meta.page_sizes.map(n => `<option ${n === cur ? "selected" : ""}>${n}</option>`).join("");

  // ------------------------------------------------------------------ approver identity (typed name, written to the audit log)
  const who = {
    get() { try { return localStorage.getItem("tg_approver") || ""; } catch (e) { return ""; } },
    set(v) { try { localStorage.setItem("tg_approver", v); } catch (e) { /* storage unavailable */ } this.render(); },
    render() {
      const n = this.get();
      $("#who-name").textContent = n || "Set your name";
      const initials = n.split(/[\s,]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");
      $("#who-avatar").innerHTML = initials ? esc(initials) : '<i data-lucide="user-round"></i>';
      icons($("#who-avatar"));
    },
    require() {
      if (this.get()) return this.get();
      $("#who-pop").hidden = false; $("#who-input").focus();
      toast("Set your name first. It is written to the audit log with every decision.", true);
      return null;
    },
  };
  $("#who-btn").addEventListener("click", () => { const p = $("#who-pop"); p.hidden = !p.hidden; if (!p.hidden) { $("#who-input").value = who.get(); $("#who-input").focus(); } });
  $("#who-save").addEventListener("click", () => { who.set($("#who-input").value.trim().slice(0, 80)); $("#who-pop").hidden = true; });
  $("#who-input").addEventListener("keydown", e => { if (e.key === "Enter") $("#who-save").click(); });
  document.addEventListener("click", e => { if (!e.target.closest(".who")) $("#who-pop").hidden = true; });

  // ------------------------------------------------------------------ shell: connection, pending, context bar
  async function loadShell() {
    try {
      const h = await call("/api/health");
      const c = $("#conn");
      c.classList.remove("bad");
      c.innerHTML = `<i data-lucide="server"></i><span>Exasol ${esc(String(h.version).split("-")[0])}</span>`;
      c.title = `Exasol ${h.version} at ${h.host} · ${h.host_label} · read query ${h.ms} ms · assistant: ${h.agent_ready ? h.agent_mode : (h.agent_error || "starting")}`;
      icons(c);
      state.health = h;
    } catch (e) {
      $("#conn").classList.add("bad");
      $("#conn").innerHTML = `<i data-lucide="server-off"></i><span>Database unreachable</span>`;
      icons($("#conn"));
    }
  }
  function setPending(n) {
    for (const id of ["#nav-pending", "#bell-count"]) {
      const el = $(id);
      el.hidden = !(Number(n) > 0);
      el.textContent = fmt.n(n);
    }
    $("#bell").setAttribute("aria-label", `${fmt.n(n)} actions waiting for approval`);
  }
  function setContext(o) {
    $("#ctx-window span").textContent = `Transactions ${fmt.day(o.volume.FIRST_DT)} – ${fmt.dayLong(o.volume.LAST_DT)} · cut-off ${fmt.dt(o.as_of)}`;
    $("#ctx-run span").textContent = o.last_recon ? `Last reconciliation ${fmt.dt(o.last_recon)}` : "No reconciliation run logged";
    setPending(o.pending);
  }

  // ------------------------------------------------------------------ router
  const state = { meta: null, health: null, thread: [], selected: new Set() };
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, qs] = h.split("?");
    return { page: path || "dashboard", params: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function go(page, params = {}) {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)).toString();
    location.hash = `#/${page}${qs ? "?" + qs : ""}`;
  }
  const PAGES = {};
  async function route() {
    if (!state.meta) return;   // boot calls route() once /api/meta has loaded
    const { page, params } = parseHash();
    const render = PAGES[page] || PAGES.dashboard;
    $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.page === (PAGES[page] ? page : "dashboard")));
    const app = $("#app");
    app.innerHTML = `<div class="loading">Loading…</div>`;
    try {
      await render(app, params);
    } catch (e) {
      app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
    }
    icons(app);
    if (params.open) openTxn(params.open);
  }
  window.addEventListener("hashchange", route);
  $("#refresh").addEventListener("click", () => { loadShell(); route(); });

  const head = (h, p, right = "") => `<div class="page-head"><div><h1>${h}</h1><p>${p}</p></div><div class="row">${right}</div></div>`;
  const card = (title, icon, body, extra = "", foot = "") => `<section class="card">
      <div class="card-head"><h3><span class="hicon"><i data-lucide="${icon}"></i></span>${title}</h3><div class="row">${extra}</div></div>
      <div class="card-body">${body}</div>${foot ? `<div class="card-foot">${foot}</div>` : ""}</section>`;

  // ------------------------------------------------------------------ charts (SVG, drawn from API values only)
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  function spark(values, color) {
    const vals = values.map(Number).filter(v => !Number.isNaN(v));
    if (vals.length < 2) return "";
    const W = 160, H = 34, max = Math.max(...vals), min = Math.min(...vals);
    const pts = vals.map((v, i) => [i * W / (vals.length - 1), H - 3 - (max === min ? (H - 6) / 2 : (v - min) / (max - min) * (H - 6))]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    return `<svg class="kpi-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${d} L${W} ${H} L0 ${H} Z" fill="${color}" opacity=".08"></path>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"></path></svg>`;
  }

  function trendChart(points) {
    if (!points.length) return `<div class="empty">No debit-no-credit cases.</div>`;
    const W = 640, H = 250, L = 58, R = 18, T = 14, B = 30;
    const max = niceMax(Math.max(...points.map(p => Number(p.ACCRUED_RS)), 0));
    const x = i => L + (points.length === 1 ? 0 : i * (W - L - R) / (points.length - 1));
    const y = v => T + (H - T - B) * (1 - Number(v) / max);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => f * max);
    const path = key => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");
    const real = points.filter(p => !Number(p.PROJECTED));
    const lastReal = real.length - 1;
    const solid = key => points.slice(0, lastReal + 1).map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");
    const proj = key => lastReal >= 0 && lastReal < points.length - 1 ? `M${x(lastReal)} ${y(points[lastReal][key])} ` + points.slice(lastReal + 1).map((p, j) => `L${x(lastReal + 1 + j)} ${y(p[key])}`).join(" ") : "";
    const area = `${path("OPEN_RS")} L${x(points.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`;
    return `<div class="chart-wrap" id="trend-wrap"><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Compensation liability by day">
      ${ticks.map(t => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"></line><text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${fmt.rsShort(t)}</text>`).join("")}
      ${points.map((p, i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${fmt.day(p.D)}${Number(p.PROJECTED) ? "*" : ""}</text>`).join("")}
      <path d="${area}" fill="#0F6B5C" opacity=".07"></path>
      <path d="${solid("ACCRUED_RS")}" fill="none" stroke="#98A2B3" stroke-width="2"></path>
      <path d="${proj("ACCRUED_RS")}" fill="none" stroke="#98A2B3" stroke-width="2" stroke-dasharray="5 5"></path>
      <path d="${solid("OPEN_RS")}" fill="none" stroke="#0F6B5C" stroke-width="2.4"></path>
      <path d="${proj("OPEN_RS")}" fill="none" stroke="#0F6B5C" stroke-width="2.4" stroke-dasharray="5 5"></path>
      ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.OPEN_RS)}" r="3.5" fill="${Number(p.PROJECTED) ? "#fff" : "#0F6B5C"}" stroke="#0F6B5C" stroke-width="1.6"></circle>`).join("")}
      <line id="trend-guide" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#D0D5DD" stroke-dasharray="3 3" visibility="hidden"></line>
      ${points.map((p, i) => `<rect class="hit" data-i="${i}" x="${x(i) - (W - L - R) / Math.max(points.length - 1, 1) / 2}" y="${T}" width="${(W - L - R) / Math.max(points.length - 1, 1)}" height="${H - T - B}" fill="transparent"></rect>`).join("")}
    </svg><div class="tooltip" id="trend-tip" hidden></div></div>`;
  }
  function bindTrend(points) {
    const wrap = $("#trend-wrap");
    if (!wrap) return;
    const svg = $("svg", wrap), tip = $("#trend-tip"), guide = $("#trend-guide");
    $$(".hit", svg).forEach(r => {
      r.addEventListener("mouseenter", () => {
        const p = points[Number(r.dataset.i)];
        const cx = Number(r.getAttribute("x")) + Number(r.getAttribute("width")) / 2;
        guide.setAttribute("x1", cx); guide.setAttribute("x2", cx); guide.setAttribute("visibility", "visible");
        const box = svg.getBoundingClientRect(), scale = box.width / svg.viewBox.baseVal.width;
        tip.hidden = false;
        tip.style.left = `${cx * scale}px`; tip.style.top = `${20 * scale}px`;
        tip.innerHTML = `<b>${fmt.dayLong(p.D)}${Number(p.PROJECTED) ? " · projected" : ""}</b><br>Owed on open cases: ${fmt.rs(p.OPEN_RS)}<br>Accrued, all cases: ${fmt.rs(p.ACCRUED_RS)}<br>Open cases: ${fmt.n(p.OPEN_CASES)}`;
      });
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; guide.setAttribute("visibility", "hidden"); });
  }

  function donut(classes, total) {
    const R = 62, C = 2 * Math.PI * R;
    let off = 0;
    const arcs = classes.map(c => {
      const frac = Number(c.N) / Math.max(Number(total), 1), len = frac * C;
      const s = `<circle r="${R}" cx="85" cy="85" fill="none" stroke="${classMeta(c.CLASS).color}" stroke-width="22" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 85 85)"><title>${esc(classMeta(c.CLASS).label)}: ${fmt.n(c.N)}</title></circle>`;
      off += len;
      return s;
    }).join("");
    return `<div class="donut-wrap"><svg viewBox="0 0 170 170" class="chart" role="img" aria-label="Exceptions by break type">
        <circle r="${R}" cx="85" cy="85" fill="none" stroke="#F2F4F7" stroke-width="22"></circle>${arcs}
        <text x="85" y="82" text-anchor="middle" style="font:600 20px var(--font);fill:#101828">${fmt.n(total)}</text>
        <text x="85" y="101" text-anchor="middle" style="font:12px var(--font);fill:#667085">exceptions</text></svg>
      <div class="donut-legend">${classes.map(c => `<button type="button" data-class="${esc(c.CLASS)}" title="Open in work queue">
        <span class="dot" style="background:${classMeta(c.CLASS).color}"></span><span>${esc(classMeta(c.CLASS).label)}</span>
        <span class="n">${fmt.n(c.N)}</span><span class="p">${fmt.pct(c.PCT)}</span></button>`).join("")}</div></div>`;
  }

  // ------------------------------------------------------------------ shared table bits
  function queueRow(r, opts = {}) {
    const act = r.PROPOSE_ACTION;   // decided by the backend with the same rule it checks on propose
    const actionCell = r.PENDING_ACTION_ID
      ? `<a class="pill warn" href="#/actions?status=PROPOSED" title="${esc(r.PENDING_ACTION_ID)}">Awaiting approval</a>`
      : (act ? `<button class="btn sm" data-propose="${esc(act)}" data-ref="${esc(r.EXC_ID)}" type="button"><i data-lucide="${actionMeta(act).icon}"></i>${esc(actionMeta(act).cta)}</button>` : `<span class="subtle">–</span>`);
    return `<tr class="clickable" data-open="${esc(r.EXC_ID)}">
      ${opts.select ? `<td onclick="event.stopPropagation()"><input type="checkbox" data-sel="${esc(r.EXC_ID)}" data-kind="${esc(act || "")}" ${act && !r.PENDING_ACTION_ID ? "" : "disabled"} ${state.selected.has(r.EXC_ID) ? "checked" : ""} aria-label="Select ${esc(r.EXC_ID)}"></td>` : ""}
      <td class="n">${fmt.n(r.QUEUE_RANK)}</td>
      <td><div class="mono">${esc(r.UPI_TXN_ID || r.EXC_ID)}</div><div class="subtle" style="font-size:12px">${fmt.dt(r.TXN_TIME)}${r.RRN ? " · RRN " + esc(r.RRN) : ""}</div></td>
      <td>${esc(r.TXN_TYPE || "–")}</td>
      <td class="n">${fmt.rs(r.AMOUNT_RS)}</td>
      <td>${classTag(r.CLASS)}</td>
      <td>${statePill(r.TAT_STATE)}${r.DEADLINE_DT ? `<div class="subtle" style="font-size:12px;margin-top:3px">deadline ${fmt.day(r.DEADLINE_DT)}</div>` : ""}</td>
      <td class="n"><b>${fmt.rs(r.OWED_TOMORROW_RS)}</b>${Number(r.NEW_ACCRUAL_RS) > 0 ? `<div class="c-danger" style="font-size:12px">+${fmt.rs(r.NEW_ACCRUAL_RS)} by tomorrow</div>` : ""}</td>
      <td onclick="event.stopPropagation()">${actionCell}</td></tr>`;
  }
  const queueHeader = (select) => `<thead><tr>${select ? `<th style="width:34px"><input type="checkbox" id="sel-all" aria-label="Select all eligible rows"></th>` : ""}
      <th class="n">#</th><th>Transaction</th><th>Type</th><th class="n">Amount</th><th>Break type</th><th>TAT state</th><th class="n">Owed tomorrow</th><th>Action</th></tr></thead>`;

  async function propose(kind, refs) {
    const user = who.require();
    if (!user) return false;
    try {
      const r = await call("/api/propose", { action_type: kind, targets: refs, user });
      const ok = r.results.filter(x => !x.error), bad = r.results.filter(x => x.error);
      if (ok.length) toast(`${ok.length} ${ok.length === 1 ? "proposal" : "proposals"} waiting for approval on the Actions page.`);
      if (bad.length) toast(esc(bad[0].error) + (bad.length > 1 ? ` (+${bad.length - 1} more)` : ""), true);
      loadShell(); refreshPending();
      return true;
    } catch (e) { toast(esc(e.message), true); return false; }
  }
  async function refreshPending() {
    try { const a = await call("/api/actions?status=PROPOSED"); setPending(a.counts.PROPOSED || 0); } catch (e) { /* header badge only */ }   // rows are capped at 200; counts are not
  }

  function bindRowClicks(root) {
    $$("tr[data-open]", root).forEach(tr => tr.addEventListener("click", () => openTxn(tr.dataset.open)));
    $$("button[data-propose]", root).forEach(b => b.addEventListener("click", async () => {
      b.disabled = true;
      if (await propose(b.dataset.propose, [b.dataset.ref])) route(); else b.disabled = false;
    }));
  }

  // ------------------------------------------------------------------ page: dashboard
  PAGES.dashboard = async (app) => {
    const [o, t, top, act] = await Promise.all([call("/api/overview"), call("/api/trend"), call("/api/queue?sort=rank&size=10"), call("/api/activity?n=6")]);
    setContext(o);
    const k = o.kpi, v = o.volume;
    const kpis = [
      { tone: "brand", icon: "indian-rupee", label: "Owed tomorrow if unreversed", value: fmt.rs(k.OWED_TOMORROW_RS),
        sub: `+${fmt.rs(k.NEW_ACCRUAL_RS)} new by tomorrow · ${fmt.n(k.OPEN_CASES)} open cases`, spark: spark(t.points.map(p => p.OPEN_RS), "#0F6B5C"), go: ["queue", { sort: "owed" }] },
      { tone: "danger", icon: "clock-alert", label: "Overdue", value: fmt.n(k.OVERDUE_N), sub: `${fmt.rs(k.OVERDUE_RS)} accrued past the deadline`, go: ["queue", { state: "OVERDUE" }] },
      { tone: "warn", icon: "triangle-alert", label: "At risk by tomorrow", value: fmt.n(k.AT_RISK_N), sub: `${fmt.rs(k.AT_RISK_RS)} owed tomorrow if not reversed`, go: ["queue", { state: "AT_RISK" }] },
      { tone: "info", icon: "list-checks", label: "Exceptions", value: fmt.n(v.EXCEPTIONS), sub: `${fmt.pct(v.EXCEPTION_PCT)} of ${fmt.n(v.TXNS)} transactions`, spark: spark(o.daily.map(d => d.N), "#1D4F91"), go: ["queue", {}] },
      { tone: "violet", icon: "hand-coins", label: "Compensation due", value: fmt.rs(k.COMP_DUE_RS), sub: `${fmt.n(k.COMP_DUE_N)} reversed cases missing or underpaid`, go: ["queue", { state: "COMPENSATION_DUE" }] },
    ];
    const tatBlock = o.tat.map(tt => {
      const tot = Math.max(Number(tt.TOTAL), 1);
      const seg = (n, cls) => `<span class="${cls}" style="width:${100 * Number(n) / tot}%"></span>`;
      return `<div class="tat-type"><h4><span>${esc(tt.TXN_TYPE)} <span class="muted" style="font-weight:500">(T+${fmt.n(tt.TAT_DAYS)} days)</span></span><span>${fmt.n(tt.TOTAL)}</span></h4>
        <div class="stack">${seg(tt.OVERDUE, "bg-danger")}${seg(tt.AT_RISK, "bg-warn")}${seg(tt.WITHIN_TAT, "bg-info")}${seg(tt.REVERSED, "bg-neutral")}</div>
        <div class="tat-nums">
          <button data-go-state="OVERDUE"><b class="c-danger">${fmt.n(tt.OVERDUE)}</b><small>Overdue</small></button>
          <button data-go-state="AT_RISK"><b class="c-warn">${fmt.n(tt.AT_RISK)}</b><small>At risk</small></button>
          <button data-go-state="WITHIN_TAT"><b class="c-info">${fmt.n(tt.WITHIN_TAT)}</b><small>Within TAT</small></button>
          <button data-go-state="COMPENSATION_DUE" title="Opens the ${fmt.n(tt.COMP_DUE)} reversed cases whose compensation is missing or short"><b>${fmt.n(tt.REVERSED)}</b><small>Reversed · ${fmt.n(tt.COMP_DUE)} comp. due</small></button>
        </div></div>`;
    }).join("");
    const rates = [...new Set(o.rules.map(r => String(r.RS_PER_DAY)))];   // one rate today; show each if rules ever differ
    const rulesLine = o.rules.map(r => `${esc(r.TXN_TYPE)} T+${fmt.n(r.TAT_DAYS)}${rates.length > 1 ? ` at ${fmt.rs(r.RS_PER_DAY)}/day` : ""}`).join(" · ")
      + (rates.length === 1 ? ` · ${fmt.rs(rates[0])}/day beyond` : "") + (o.rules.length ? ` (${esc(o.rules.map(r => r.FACT_ID).join(", "))})` : "");
    const acts = act.items.length ? act.items.map(activityItem).join("") : `<div class="empty">No proposals or approvals yet.</div>`;
    app.innerHTML = head("Dashboard", "Reconcile UPI transactions, track TAT exposure, and resolve the costliest exceptions first.") + `
      <div class="kpis">${kpis.map((c, i) => `<button class="kpi tone-${c.tone}" data-kpi="${i}" type="button">
          <div class="kpi-top"><span class="kpi-icon"><i data-lucide="${c.icon}"></i></span><span class="kpi-label">${esc(c.label)}</span></div>
          <div class="kpi-value">${c.value}</div><div class="kpi-sub">${c.sub}</div>${c.spark || ""}</button>`).join("")}</div>
      <div class="grid">
        <div class="span-5">${card("Compensation liability by day", "chart-line", trendChart(t.points) + `<div class="legend" style="margin-top:8px">
            <span><i class="sw" style="background:#0F6B5C"></i>Owed on cases still open</span><span><i class="sw" style="background:#98A2B3"></i>Accrued on all cases</span>
            <span><i class="sw dash"></i>* tomorrow, projected</span></div>`, "", `<span>Penalty days = calendar days beyond T+TAT, per case, up to its reversal</span><span class="timing">${t.ms} ms</span>`)}</div>
        <div class="span-4">${card("Exceptions by break type", "chart-pie", donut(o.classes, v.EXCEPTIONS), "", `<span>Select a type to open it in the work queue</span><span class="timing">${o.ms.classes} ms</span>`)}</div>
        <div class="span-3">${card("TAT status by type", "timer", tatBlock || `<div class="empty">No debit-no-credit cases.</div>`, `<a class="btn ghost sm" href="#/queue?class=DEBIT_NO_CREDIT">View<i data-lucide="arrow-right"></i></a>`, `<span>${rulesLine}</span>`)}</div>
        <div class="span-8"><section class="card">
          <div class="card-head"><h3><span class="hicon"><i data-lucide="list-ordered"></i></span>Highest exposure first</h3><a class="btn sm" href="#/queue">Open work queue<i data-lucide="arrow-right"></i></a></div>
          <div class="table-wrap" style="margin-top:12px"><table class="data">${queueHeader(false)}<tbody>${top.rows.slice(0, 6).map(r => queueRow(r)).join("")}</tbody></table></div>
          <div class="card-foot"><span>Ranked by rupees owed tomorrow, then amount · ${fmt.n(top.total)} rows in the queue</span><span class="timing">${top.ms} ms</span></div></section></div>
        <div class="span-4" style="display:grid;gap:16px;align-content:start">
          ${card("Ask the assistant", "message-square-text", `<div class="suggest">${state.meta.suggestions.map(s => `<button type="button" data-ask="${esc(s)}"><span>${esc(s)}</span><i data-lucide="arrow-right"></i></button>`).join("")}</div>
            <form class="askbox" id="dash-ask"><input name="q" placeholder="Ask about the data…" maxlength="500" aria-label="Question"><button class="btn primary" type="submit" aria-label="Ask"><i data-lucide="send"></i></button></form>`, `<span class="muted" style="font-size:12px">Read-only through the Exasol MCP server</span>`)}
          ${card("Recent activity", "activity", `<div class="activity">${acts}</div>`, `<a class="btn ghost sm" href="#/audit">Audit log<i data-lucide="arrow-right"></i></a>`)}
        </div>
      </div>`;
    $$("[data-kpi]", app).forEach(b => b.addEventListener("click", () => go(...kpis[Number(b.dataset.kpi)].go)));
    $$("[data-class]", app).forEach(b => b.addEventListener("click", () => go("queue", { class: b.dataset.class })));
    $$("[data-go-state]", app).forEach(b => b.addEventListener("click", () => go("queue", { state: b.dataset.goState, class: "DEBIT_NO_CREDIT" })));
    $$("[data-ask]", app).forEach(b => b.addEventListener("click", () => go("assistant", { ask: b.dataset.ask })));
    $("#dash-ask").addEventListener("submit", e => { e.preventDefault(); const v = e.target.q.value.trim(); if (v) go("assistant", { ask: v }); });
    bindRowClicks(app);
    bindTrend(t.points);
  };

  function activityItem(a) {
    const kind = { PROPOSED: ["Proposed", "file-plus", "warn"], APPROVED: ["Approved", "check", "info"], REJECTED: ["Rejected", "x", "neutral"],
      EXECUTED: ["Executed", "circle-check", "brand"], LOGGED: ["Logged for operations", "clipboard-check", "brand"], FAILED: ["Failed", "circle-x", "danger"] }[a.KIND] || [title(a.KIND), "info", "neutral"];
    const tone = { warn: "var(--warn-soft);color:var(--warn)", info: "var(--info-soft);color:var(--info)", neutral: "var(--neutral-soft);color:var(--muted)",
      brand: "var(--brand-soft);color:var(--brand)", danger: "var(--danger-soft);color:var(--danger)" }[kind[2]];
    return `<div class="act"><span class="ic" style="background:${tone}"><i data-lucide="${kind[1]}"></i></span>
      <div><b>${esc(kind[0])}: ${esc(actionMeta(a.ACTION_TYPE).label)}</b><p class="wrap">${esc(a.TARGET_REF)} · ${esc(a.WHO || "")}</p></div>
      <time title="${esc(a.TS)}">${fmt.ago(a.TS)}</time></div>`;
  }

  // ------------------------------------------------------------------ page: work queue
  PAGES.queue = async (app, p) => {
    const params = { state: p.state || "", class: p.class || "", q: p.q || "", sort: p.sort || state.meta.queue_sorts[0], page: p.page || "1", size: p.size || String(state.meta.default_page_size) };
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    const r = await call("/api/queue?" + qs);
    state.selected = new Set([...state.selected].filter(id => r.rows.some(x => x.EXC_ID === id)));
    const all = Object.values(r.tabs).reduce((a, b) => a + Number(b), 0);
    const tabs = [["", "All", all], ...state.meta.tat_states.map(s => [s, (STATE_META[s] || { label: title(s) }).label, r.tabs[s] || 0])];
    const pages = Math.max(1, Math.ceil(Number(r.total) / r.size));
    const csvQs = new URLSearchParams(Object.entries({ state: params.state, class: params.class, q: params.q }).filter(([, v]) => v)).toString();
    app.innerHTML = head("Work Queue", "Every open exception, plus reversed cases whose compensation is missing. Ranked by rupees owed tomorrow.",
      `<a class="btn" href="/api/queue.csv${csvQs ? "?" + csvQs : ""}" download><i data-lucide="download"></i>Export CSV</a>`) + `
      <section class="card">
        <div class="tabs">${tabs.map(([s, l, n]) => `<button class="tab ${params.state === s ? "active" : ""}" data-tab="${s}" type="button">${esc(l)} <em>${fmt.n(n)}</em></button>`).join("")}</div>
        <form class="toolbar" id="qf">
          <label class="search"><i data-lucide="search"></i><input name="q" value="${esc(params.q)}" placeholder="Search by UPI id, RRN or exception id" maxlength="40"></label>
          <select name="class" aria-label="Break type"><option value="">All break types</option>${r.classes.map(c => `<option value="${esc(c)}" ${c === params.class ? "selected" : ""}>${esc(classMeta(c).label)}</option>`).join("")}</select>
          <select name="sort" aria-label="Sort">${state.meta.queue_sorts.map(v => `<option value="${esc(v)}" ${v === params.sort ? "selected" : ""}>Sort: ${esc(SORT_LABEL[v] || title(v).toLowerCase())}</option>`).join("")}</select>
          <button class="btn" type="submit"><i data-lucide="filter"></i>Apply</button>
          ${params.q || params.class ? `<button class="btn ghost" type="button" id="qclear">Clear</button>` : ""}
        </form>
        <div class="bulkbar" id="bulk" hidden></div>
        <div class="table-wrap"><table class="data">${queueHeader(true)}<tbody>${r.rows.map(x => queueRow(x, { select: true })).join("") || `<tr><td colspan="9"><div class="empty">Nothing matches these filters.</div></td></tr>`}</tbody></table></div>
        <div class="pager"><span>Showing ${fmt.n(r.rows.length ? (r.page - 1) * r.size + 1 : 0)}–${fmt.n((r.page - 1) * r.size + r.rows.length)} of ${fmt.n(r.total)} · <span class="timing">${r.ms} ms</span></span>
          <div class="row"><select id="psize" aria-label="Rows per page">${sizeOptions(r.size)}</select>${pager(r.page, pages)}</div></div>
      </section>`;
    const set = (patch) => go("queue", { ...params, ...patch });
    $$("[data-tab]", app).forEach(b => b.addEventListener("click", () => set({ state: b.dataset.tab, page: 1 })));
    $("#qf").addEventListener("submit", e => { e.preventDefault(); const f = e.target; set({ q: f.q.value.trim(), class: f.class.value, sort: f.sort.value, page: 1 }); });
    $("#qf select[name=class]").addEventListener("change", () => $("#qf").requestSubmit());
    $("#qf select[name=sort]").addEventListener("change", () => $("#qf").requestSubmit());
    if ($("#qclear")) $("#qclear").addEventListener("click", () => set({ q: "", class: "", page: 1 }));
    $("#psize").addEventListener("change", e => set({ size: e.target.value, page: 1 }));
    $$("[data-page-to]", app).forEach(b => b.addEventListener("click", () => set({ page: b.dataset.pageTo })));
    bindRowClicks(app);
    const syncBulk = () => {
      const sel = $$("input[data-sel]:checked", app);
      const byKind = {};
      sel.forEach(c => (byKind[c.dataset.kind] = byKind[c.dataset.kind] || []).push(c.dataset.sel));
      state.selected = new Set(sel.map(c => c.dataset.sel));
      const bar = $("#bulk");
      bar.hidden = !sel.length;
      bar.innerHTML = `<b>${fmt.n(sel.length)} selected</b>` + Object.entries(byKind).map(([kind, ids]) =>
        `<button class="btn primary sm" data-bulk="${esc(kind)}" type="button"><i data-lucide="${actionMeta(kind).icon}"></i>${esc(actionMeta(kind).cta)} for ${fmt.n(ids.length)}</button>`).join("") +
        `<button class="btn ghost sm" id="bulk-clear" type="button">Clear selection</button>`;
      icons(bar);
      $$("[data-bulk]", bar).forEach(b => b.addEventListener("click", async () => { b.disabled = true; if (await propose(b.dataset.bulk, byKind[b.dataset.bulk])) { state.selected.clear(); route(); } else b.disabled = false; }));
      if ($("#bulk-clear")) $("#bulk-clear").addEventListener("click", () => { $$("input[data-sel]", app).forEach(c => (c.checked = false)); syncBulk(); });
    };
    $$("input[data-sel]", app).forEach(c => c.addEventListener("change", syncBulk));
    $("#sel-all").addEventListener("change", e => { $$("input[data-sel]:not(:disabled)", app).forEach(c => (c.checked = e.target.checked)); syncBulk(); });
    syncBulk();
  };
  function pager(page, pages) {
    const nums = new Set([1, pages, page - 1, page, page + 1].filter(n => n >= 1 && n <= pages));
    const list = [...nums].sort((a, b) => a - b);
    let out = `<div class="pages"><button data-page-to="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="Previous page"><i data-lucide="chevron-left"></i></button>`;
    list.forEach((n, i) => { if (i && n - list[i - 1] > 1) out += `<button disabled>…</button>`; out += `<button data-page-to="${n}" class="${n === page ? "cur" : ""}">${fmt.n(n)}</button>`; });
    return out + `<button data-page-to="${page + 1}" ${page >= pages ? "disabled" : ""} aria-label="Next page"><i data-lucide="chevron-right"></i></button></div>`;
  }

  // ------------------------------------------------------------------ page: transactions
  PAGES.transactions = async (app, p) => {
    const params = { q: p.q || "", outcome: p.outcome || "", page: p.page || "1", size: p.size || String(state.meta.default_page_size) };
    const r = await call("/api/transactions?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString());
    const pages = Math.max(1, Math.ceil(Number(r.total) / r.size));
    app.innerHTML = head("Transactions", "Every UPI transaction as the reconciliation sees it: switch log, NPCI settlement and core-banking debits.") + `
      <section class="card">
        <div class="tabs">${[["", "All"], ["exception", "With an exception"], ["clean", "Reconciled"]].map(([v, l]) => `<button class="tab ${params.outcome === v ? "active" : ""}" data-outcome="${v}" type="button">${l}</button>`).join("")}</div>
        <form class="toolbar" id="tf"><label class="search"><i data-lucide="search"></i><input name="q" value="${esc(params.q)}" placeholder="Search by UPI id or RRN (prefix works)" maxlength="40"></label>
          <button class="btn" type="submit"><i data-lucide="search"></i>Search</button>${params.q ? `<button class="btn ghost" type="button" id="tclear">Clear</button>` : ""}</form>
        <div class="table-wrap"><table class="data"><thead><tr><th>Time</th><th>UPI transaction id</th><th>RRN</th><th>Type</th><th>Payee bank</th><th class="n">Amount</th><th>Switch</th><th>NPCI</th><th class="n">CBS debits</th><th>Result</th></tr></thead>
          <tbody>${r.rows.map(t => `<tr class="clickable" data-open="${esc(t.UPI_TXN_ID || t.RRN)}">
            <td>${fmt.dt(t.TXN_TIME)}</td><td class="mono">${esc(t.UPI_TXN_ID || "–")}</td><td class="mono">${esc(t.RRN)}</td><td>${esc(t.TXN_TYPE || "–")}</td><td>${esc(t.PAYEE_BANK || "–")}</td>
            <td class="n">${fmt.rs(t.AMOUNT_RS)}</td><td>${esc(title(t.SW_STATUS) || "–")}</td><td>${t.NPCI_STATUS ? esc(title(t.NPCI_STATUS)) : `<span class="subtle">no record</span>`}</td>
            <td class="n">${fmt.n(t.DR_CNT)}</td><td>${t.CLASS ? classTag(t.CLASS) : pill("Reconciled", "brand")}</td></tr>`).join("") || `<tr><td colspan="10"><div class="empty">No transaction matches.</div></td></tr>`}</tbody></table></div>
        <div class="pager"><span>Showing ${fmt.n(r.rows.length ? (r.page - 1) * r.size + 1 : 0)}–${fmt.n((r.page - 1) * r.size + r.rows.length)} of ${fmt.n(r.total)} · <span class="timing">${r.ms} ms</span></span>
          <div class="row"><select id="tsize" aria-label="Rows per page">${sizeOptions(r.size)}</select>${pager(r.page, pages)}</div></div>
      </section>`;
    const set = patch => go("transactions", { ...params, ...patch });
    $$("[data-outcome]", app).forEach(b => b.addEventListener("click", () => set({ outcome: b.dataset.outcome, page: 1 })));
    $("#tf").addEventListener("submit", e => { e.preventDefault(); set({ q: e.target.q.value.trim(), page: 1 }); });
    if ($("#tclear")) $("#tclear").addEventListener("click", () => set({ q: "", page: 1 }));
    $("#tsize").addEventListener("change", e => set({ size: e.target.value, page: 1 }));
    $$("[data-page-to]", app).forEach(b => b.addEventListener("click", () => set({ page: b.dataset.pageTo })));
    bindRowClicks(app);
  };

  // ------------------------------------------------------------------ page: assistant
  PAGES.assistant = async (app, p) => {
    const h = state.health || await call("/api/health");
    app.innerHTML = head("Assistant", "Ask about the reconciliation. Answers come only from SQL run on Exasol, and every query is shown.") + `
      <div class="grid"><div class="span-8"><section class="card"><div class="card-body">
          <div class="thread" id="thread"></div>
          <form class="askbox" id="ask-form"><input name="q" placeholder="e.g. Why did breaks spike?" maxlength="500" aria-label="Question" autocomplete="off"><button class="btn primary" type="submit"><i data-lucide="send"></i>Ask</button></form>
          <div class="row" style="flex-wrap:wrap;margin-top:10px">${state.meta.suggestions.map(s => `<button class="btn sm" type="button" data-ask="${esc(s)}">${esc(s)}</button>`).join("")}</div>
        </div></section></div>
        <div class="span-4">${card("How it answers", "shield-check", `<div class="kv" style="grid-template-columns:1fr">
            <div><dt>Mode</dt><dd>${h.agent_ready ? (h.agent_mode === "gemini" ? "Google Gemini, with read-only tools" : "Deterministic playbooks (no language model configured)") : esc(h.agent_error || "Starting…")}</dd></div>
            <div><dt>Reads</dt><dd>Through the official Exasol MCP server, as a database user that can only SELECT</dd></div>
            <div><dt>Numbers</dt><dd>Every number in an answer is checked against that turn's query results before it is shown</dd></div>
            <div><dt>Changes</dt><dd>The assistant can only propose. A named person approves on the Actions page</dd></div></div>`)}</div></div>`;
    const render = () => {
      $("#thread").innerHTML = state.thread.length ? state.thread.map(m => m.q ? `<div class="msg-q">${esc(m.q)}</div>` : answerHtml(m)).join("") : `<div class="empty">Ask a question, or pick one below.</div>`;
      icons($("#thread"));
      $$("[data-open]", $("#thread")).forEach(b => b.addEventListener("click", () => openTxn(b.dataset.open)));
    };
    const ask = async (text) => {
      state.thread.push({ q: text }, { pending: true });
      render();
      try { const a = await call("/api/ask", { question: text }); state.thread[state.thread.length - 1] = a; refreshPending(); }
      catch (e) { state.thread[state.thread.length - 1] = { error: e.message }; }
      render();
    };
    $("#ask-form").addEventListener("submit", e => { e.preventDefault(); const v = e.target.q.value.trim(); if (v) { e.target.q.value = ""; ask(v); } });
    $$("[data-ask]", app).forEach(b => b.addEventListener("click", () => ask(b.dataset.ask)));
    render();
    if (p.ask) { history.replaceState(null, "", "#/assistant"); ask(p.ask); }
  };
  function answerHtml(a) {
    if (a.pending) return `<div class="msg-a"><div class="answer muted">Running SQL on Exasol through the MCP server…</div></div>`;
    if (a.error) return `<div class="msg-a"><div class="error-box">${esc(a.error)}</div></div>`;
    const q = (a.queries || []).map((r, i) => `<details class="sql"><summary><span>Query ${i + 1} · ${fmt.n(r.row_count)} rows</span><span class="timing">${fmt.n(r.ms)} ms</span></summary><pre>${esc(r.sql)}</pre>
      <div class="table-wrap" style="max-height:220px"><table class="data"><thead><tr>${r.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${r.rows.map(row => `<tr>${row.map(v => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`).join("");
    const prop = a.proposal ? (a.proposal.error ? `<span class="c-danger">Proposal refused: ${esc(a.proposal.error)}