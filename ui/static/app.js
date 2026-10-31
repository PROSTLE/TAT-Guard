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
    OVERDUE: { label: "Overdue", tone: "danger" }, AT_RISK: { label: "Due today", tone: "warn" },
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
  const COMP_META = { PAID: { label: "Paid in full", tone: "brand" }, UNDERPAID: { label: "Underpaid", tone: "warn" }, MISSING: { label: "Not paid", tone: "danger" },
    ACCRUING: { label: "Still accruing", tone: "info" }, NOT_DUE: { label: "Not due", tone: "neutral" } };
  const FOCUS_LABEL = { accruing: "Adding cost tomorrow" };
  const SORT_LABEL = { rank: "priority", owed: "owed tomorrow", amount: "amount", time: "most recent", deadline: "earliest deadline" };
  const pill = (text, tone) => `<span class="pill ${tone}">${esc(text)}</span>`;
  const statePill = s => s ? pill((STATE_META[s] || { label: title(s) }).label, (STATE_META[s] || { tone: "neutral" }).tone) : "";
  const classTag = c => `<span class="cls"><i style="background:${classMeta(c).color}"></i>${esc(classMeta(c).label)}</span>`;
  const plural = (n, one, many) => `${fmt.n(n)} ${Number(n) === 1 ? one : (many || one + "s")}`;
  // days from the cut-off to the deadline, computed in SQL (negative = past it)
  const clockText = d => { if (!isNum(d)) return ""; const n = Number(d); return n < 0 ? `${plural(-n, "day")} overdue` : n === 0 ? "Due today" : `${plural(n, "day")} left`; };
  const errorBox = msg => `<div class="error-box"><div>${esc(msg)}</div><button class="btn sm" type="button" data-retry><i data-lucide="refresh-cw"></i>Try again</button></div>`;
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
  $("#who-save").addEventListener("click", () => { who.set($("#who-input").value.trim().slice(0, 80)); $("#who-pop").hidden = true; if (parseHash().page === "actions") route(); });
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
      $("#offline").hidden = true;
    } catch (e) {
      $("#offline").hidden = false;
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
    const took = isNum(o.recon_ms) ? ` · took ${fmt.n(Math.round(Number(o.recon_ms) / 100) / 10)} s` : "";
    $("#ctx-run span").textContent = o.last_recon ? `Last reconciliation ${fmt.dt(o.last_recon)}${took}` : "No reconciliation run logged";
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
    $$("#nav a").forEach(a => {
      const on = a.dataset.page === (PAGES[page] ? page : "dashboard");
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const app = $("#app");
    app.innerHTML = `<div class="skeleton" role="status" aria-label="Loading"><i></i><i></i><i></i></div>`;
    try {
      await render(app, params);
    } catch (e) {
      app.innerHTML = errorBox(e.message);
      $("[data-retry]", app).addEventListener("click", () => { loadShell(); route(); });
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
    const days = Number(r.DAYS_TO_DEADLINE);
    const clock = r.TAT_STATE === "COMPENSATION_DUE" ? `${fmt.rs(r.COMP_GAP_RS)} still owed`
      : r.TAT_STATE === "OVERDUE" ? `${plural(-days, "day")} past ${fmt.day(r.DEADLINE_DT)}`
      : r.TAT_STATE === "AT_RISK" ? `Reverse by ${fmt.day(r.DEADLINE_DT)}` : clockText(r.DAYS_TO_DEADLINE);
    return `<tr class="clickable" data-open="${esc(r.EXC_ID)}" tabindex="0" aria-label="Open case ${esc(r.UPI_TXN_ID || r.EXC_ID)}">
      ${opts.select ? `<td onclick="event.stopPropagation()"><input type="checkbox" data-sel="${esc(r.EXC_ID)}" data-kind="${esc(act || "")}" ${act && !r.PENDING_ACTION_ID ? "" : "disabled"} ${state.selected.has(r.EXC_ID) ? "checked" : ""} aria-label="Select ${esc(r.EXC_ID)}"></td>` : ""}
      <td class="n">${fmt.n(r.QUEUE_RANK)}</td>
      <td><div class="mono">${esc(r.UPI_TXN_ID || r.EXC_ID)}</div><div class="subtle" style="font-size:12px">${fmt.dt(r.TXN_TIME)}${r.RRN ? " · RRN " + esc(r.RRN) : ""}</div></td>
      <td>${esc(r.TXN_TYPE || "–")}</td>
      <td class="n">${fmt.rs(r.AMOUNT_RS)}</td>
      <td>${classTag(r.CLASS)}</td>
      <td>${statePill(r.TAT_STATE)}${clock ? `<div class="subtle" style="font-size:12px;margin-top:3px;white-space:nowrap">${esc(clock)}</div>` : ""}</td>
      <td class="n">${Number(r.NEW_ACCRUAL_RS) > 0 ? `<b class="c-danger">+${fmt.rs(r.NEW_ACCRUAL_RS)}</b>` : `<span class="subtle">–</span>`}</td>
      <td class="n">${Number(r.ACCRUED_RS) > 0 ? fmt.rs(r.ACCRUED_RS) : `<span class="subtle">–</span>`}</td>
      <td onclick="event.stopPropagation()">${actionCell}</td></tr>`;
  }
  const queueHeader = (select) => `<thead><tr>${select ? `<th style="width:34px"><input type="checkbox" id="sel-all" aria-label="Select all eligible rows"></th>` : ""}
      <th class="n">#</th><th>Transaction</th><th>Type</th><th class="n">Amount</th><th>Break type</th><th>Clock</th><th class="n" title="What this case adds to the compensation bill by tomorrow if it stays open">Adds tomorrow</th><th class="n">Accrued so far</th><th>Action</th></tr></thead>`;

  async function propose(kind, refs) {
    const user = who.require();
    if (!user) return false;
    try {
      const r = await call("/api/propose", { action_type: kind, targets: refs, user });
      const ok = r.results.filter(x => !x.error), bad = r.results.filter(x => x.error);
      if (ok.length) toast(`${ok.length} ${ok.length === 1 ? "proposal" : "proposals"} waiting for approval. <a href="#/actions?status=PROPOSED">Review on Actions</a>`);
      if (bad.length) toast(esc(bad[0].error) + (bad.length > 1 ? ` (+${bad.length - 1} more)` : ""), true);
      loadShell(); refreshPending();
      return true;
    } catch (e) { toast(esc(e.message), true); return false; }
  }
  async function refreshPending() {
    try { const a = await call("/api/actions?status=PROPOSED"); setPending(a.counts.PROPOSED || 0); } catch (e) { /* header badge only */ }   // rows are capped at 200; counts are not
  }

  function bindRowClicks(root) {
    $$("tr[data-open]", root).forEach(tr => {
      tr.addEventListener("click", () => openTxn(tr.dataset.open));
      tr.addEventListener("keydown", e => { if (e.key === "Enter" && e.target === tr) openTxn(tr.dataset.open); });
    });
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
    // "What needs doing": built only from live counts, so a step disappears when its work is done
    const steps = [];
    if (Number(k.ACCRUING_N) > 0) steps.push({ tone: "danger", icon: "timer", title: `Stop the clock on ${plural(k.ACCRUING_N, "case")}`,
      body: `They add ${fmt.rs(k.NEW_ACCRUAL_RS)} tomorrow. Each reversal avoids the same daily cost, so start with the customers waiting longest.`, cta: "Open these cases", go: ["queue", { focus: "accruing" }] });
    if (Number(k.COMP_DUE_N) > 0) steps.push({ tone: "violet", icon: "hand-coins", title: `Pay ${fmt.rs(k.COMP_DUE_RS)} of compensation`,
      body: `${plural(k.COMP_DUE_N, "reversed case")} still owe the customer compensation, due without waiting for a complaint.`, cta: "Open these cases", go: ["queue", { state: "COMPENSATION_DUE" }] });
    o.missing_files.forEach(f => steps.push({ tone: "warn", icon: "file-clock", title: `Chase the ${fmt.day(f.SETTLEMENT_DT)} cycle ${fmt.n(f.CYCLE_NO)} settlement file`,
      body: `Expected ${fmt.dt(f.EXPECTED)}. ${plural(f.BREAKS, "break")} cannot be confirmed until it arrives.`, cta: "See settlement files", go: ["sources", {}] }));
    if (Number(o.pending) > 0) steps.push({ tone: "info", icon: "clipboard-check", title: `Decide ${plural(o.pending, "proposal")}`,
      body: "Nothing changes until a named person approves.", cta: "Review", go: ["actions", { status: "PROPOSED" }] });
    const kpis = [
      { tone: "danger", icon: "indian-rupee", label: "Added tomorrow if nothing changes", value: fmt.rs(k.NEW_ACCRUAL_RS),
        sub: `${plural(k.ACCRUING_N, "case")} accruing · ${fmt.rs(k.OWED_TOMORROW_RS)} owed in total`, spark: spark(t.points.map(p => p.OPEN_RS), "#B42318"), go: ["queue", { focus: "accruing" }] },
      { tone: "brand", icon: "wallet", label: "Customer money stuck", value: fmt.rs(k.STUCK_RS), sub: `${plural(k.OPEN_CASES, "debit-no-credit case")} still open`, go: ["queue", { class: "DEBIT_NO_CREDIT" }] },
      { tone: "danger", icon: "clock-alert", label: "Overdue", value: fmt.n(k.OVERDUE_N), sub: `${fmt.rs(k.OVERDUE_RS)} accrued past the deadline`, go: ["queue", { state: "OVERDUE" }] },
      { tone: "warn", icon: "triangle-alert", label: "Due today", value: fmt.n(k.AT_RISK_N), sub: `Reversed today, these never start accruing`, go: ["queue", { state: "AT_RISK" }] },
      { tone: "violet", icon: "hand-coins", label: "Compensation due", value: fmt.rs(k.COMP_DUE_RS), sub: `${plural(k.COMP_DUE_N, "reversed case")} missing or underpaid`, go: ["queue", { state: "COMPENSATION_DUE" }] },
    ];
    const tatBlock = o.tat.map(tt => {
      const tot = Math.max(Number(tt.TOTAL), 1);
      const seg = (n, cls) => `<span class="${cls}" style="width:${100 * Number(n) / tot}%"></span>`;
      return `<div class="tat-type"><h4><span>${esc(tt.TXN_TYPE)} <span class="muted" style="font-weight:500">(T+${fmt.n(tt.TAT_DAYS)} days)</span></span><span>${fmt.n(tt.TOTAL)}</span></h4>
        <div class="stack">${seg(tt.OVERDUE, "bg-danger")}${seg(tt.AT_RISK, "bg-warn")}${seg(tt.WITHIN_TAT, "bg-info")}${seg(tt.REVERSED, "bg-neutral")}</div>
        <div class="tat-nums">
          <button data-go-state="OVERDUE"><b class="c-danger">${fmt.n(tt.OVERDUE)}</b><small>Overdue</small></button>
          <button data-go-state="AT_RISK"><b class="c-warn">${fmt.n(tt.AT_RISK)}</b><small>Due today</small></button>
          <button data-go-state="WITHIN_TAT"><b class="c-info">${fmt.n(tt.WITHIN_TAT)}</b><small>Within TAT</small></button>
          <button data-go-state="COMPENSATION_DUE" title="Opens the ${fmt.n(tt.COMP_DUE)} reversed cases whose compensation is missing or short"><b>${fmt.n(tt.REVERSED)}</b><small>Reversed · ${fmt.n(tt.COMP_DUE)} comp. due</small></button>
        </div></div>`;
    }).join("");
    const rates = [...new Set(o.rules.map(r => String(r.RS_PER_DAY)))];   // one rate today; show each if rules ever differ
    const rulesLine = o.rules.map(r => `${esc(r.TXN_TYPE)} T+${fmt.n(r.TAT_DAYS)}${rates.length > 1 ? ` at ${fmt.rs(r.RS_PER_DAY)}/day` : ""}`).join(" · ")
      + (rates.length === 1 ? ` · ${fmt.rs(rates[0])}/day beyond` : "") + (o.rules.length ? ` (${esc(o.rules.map(r => r.FACT_ID).join(", "))})` : "");
    const acts = act.items.length ? act.items.map(activityItem).join("") : `<div class="empty">No proposals or approvals yet.</div>`;
    const ageMax = Math.max(...o.ageing.map(a => Number(a.N)), 1);
    const ageing = o.ageing.map(a => `<div class="bar-row"><span>${Number(a.DAYS) ? `${plural(a.DAYS, "day")} past TAT` : "Not past TAT"}</span>
        <span class="bar"><i class="${Number(a.DAYS) ? "bg-danger" : "bg-info"}" style="width:${100 * Number(a.N) / ageMax}%"></i></span><b>${fmt.n(a.N)}</b><em>${fmt.rs(a.STUCK_RS)}</em></div>`).join("");
    const banks = o.banks.map(b => `<tr class="clickable" data-bank="${esc(b.BANK)}" tabindex="0" aria-label="Open ${esc(b.BANK)} cases"><td>${esc(b.BANK)}</td><td class="n">${fmt.n(b.N)}</td><td class="n">${fmt.n(b.OVERDUE_N)}</td><td class="n">${fmt.rs(b.STUCK_RS)}</td><td class="n">${Number(b.NEW_ACCRUAL_RS) > 0 ? `<b class="c-danger">+${fmt.rs(b.NEW_ACCRUAL_RS)}</b>` : "–"}</td></tr>`).join("");
    const comp = o.compensation.map(c => { const m = COMP_META[c.COMP_STATUS] || { label: title(c.COMP_STATUS), tone: "neutral" };
      return `<div class="row between comp-row"><span>${pill(m.label, m.tone)}</span><span><b>${fmt.n(c.N)}</b>${Number(c.GAP_RS) > 0 ? ` <span class="muted">· ${fmt.rs(c.GAP_RS)} short</span>` : Number(c.PAID_RS) > 0 ? ` <span class="muted">· ${fmt.rs(c.PAID_RS)} paid</span>` : ""}</span></div>`; }).join("");
    app.innerHTML = head("Dashboard", "See what adds cost tomorrow, fix that first, and prove compensation was paid.") + `
      <section class="card steps-card" aria-label="What needs doing"><div class="card-head"><h3><span class="hicon"><i data-lucide="list-todo"></i></span>What needs doing</h3></div>
        ${steps.length ? `<div class="steps">${steps.map((c, i) => `<button class="step tone-${c.tone}" data-step="${i}" type="button"><span class="kpi-icon"><i data-lucide="${c.icon}"></i></span>
            <span class="step-text"><b>${i + 1}. ${esc(c.title)}</b><span>${esc(c.body)}</span><em>${esc(c.cta)}<i data-lucide="arrow-right"></i></em></span></button>`).join("")}</div>`
          : `<div class="empty">Nothing needs action right now.</div>`}</section>
      <div class="kpis">${kpis.map((c, i) => `<button class="kpi tone-${c.tone}" data-kpi="${i}" type="button">
          <div class="kpi-top"><span class="kpi-icon"><i data-lucide="${c.icon}"></i></span><span class="kpi-label">${esc(c.label)}</span></div>
          <div class="kpi-value">${c.value}</div><div class="kpi-sub">${c.sub}</div>${c.spark || ""}</button>`).join("")}</div>
      <div class="grid">
        <div class="span-8"><section class="card">
          <div class="card-head"><h3><span class="hicon"><i data-lucide="list-ordered"></i></span>Do these first</h3><a class="btn sm" href="#/queue">Open work queue<i data-lucide="arrow-right"></i></a></div>
          <div class="table-wrap" style="margin-top:12px"><table class="data">${queueHeader(false)}<tbody>${top.rows.slice(0, 6).map(r => queueRow(r)).join("")}</tbody></table></div>
          <div class="card-foot"><span>Ranked by what a case adds tomorrow, then time waited · ${plural(top.total, "row")} in the queue</span><span class="timing">${top.ms} ms</span></div></section></div>
        <div class="span-4" style="display:grid;gap:16px;align-content:start">
          ${card("Ask the assistant", "message-square-text", `<div class="suggest">${state.meta.suggestions.map(s => `<button type="button" data-ask="${esc(s)}"><span>${esc(s)}</span><i data-lucide="arrow-right"></i></button>`).join("")}</div>
            <form class="askbox" id="dash-ask"><input name="q" placeholder="Ask about the data…" maxlength="500" aria-label="Question"><button class="btn primary" type="submit" aria-label="Ask"><i data-lucide="send"></i></button></form>`, "", `<span>Read-only through the Exasol MCP server</span>`)}
          ${card("Recent activity", "activity", `<div class="activity">${acts}</div>`, `<a class="btn ghost sm" href="#/audit">Audit log<i data-lucide="arrow-right"></i></a>`)}
        </div>
        <div class="span-4">${card("Open cases by age", "hourglass", ageing || `<div class="empty">No open debit-no-credit cases.</div>`, "", `<span>Calendar days past TAT, with customer money stuck</span><span class="timing">${o.ms.ageing} ms</span>`)}</div>
        <div class="span-4">${card("Chase list by payee bank", "landmark", banks ? `<div class="table-wrap"><table class="data"><thead><tr><th>Payee bank</th><th class="n">Open</th><th class="n">Overdue</th><th class="n">Stuck</th><th class="n">Adds</th></tr></thead><tbody>${banks}</tbody></table></div>` : `<div class="empty">No open debit-no-credit cases.</div>`, "", `<span>The beneficiary bank owns the P2P auto-reversal${(o.rules.find(r => r.TXN_TYPE === "P2P") || {}).FACT_ID ? ` (${esc(o.rules.find(r => r.TXN_TYPE === "P2P").FACT_ID)})` : ""}</span><span class="timing">${o.ms.banks} ms</span>`)}</div>
        <div class="span-4">${card("Compensation register", "badge-check", comp || `<div class="empty">No debit-no-credit cases.</div>`, `<a class="btn sm" href="/api/compensation.csv" download><i data-lucide="download"></i>Export</a>`, `<span>Every case past TAT, whether or not the customer complained</span><span class="timing">${o.ms.compensation} ms</span>`)}</div>
        <div class="span-5">${card("Compensation liability by day", "chart-line", trendChart(t.points) + `<div class="legend" style="margin-top:8px">
            <span><i class="sw" style="background:#0F6B5C"></i>Owed on cases still open</span><span><i class="sw" style="background:#98A2B3"></i>Accrued on all cases</span>
            <span><i class="sw dash"></i>* tomorrow, projected</span></div>`, "", `<span>Penalty days = calendar days beyond T+TAT, per case, up to its reversal</span><span class="timing">${t.ms} ms</span>`)}</div>
        <div class="span-4">${card("Exceptions by break type", "chart-pie", donut(o.classes, v.EXCEPTIONS), "", `<span>${fmt.pct(v.EXCEPTION_PCT)} of ${fmt.n(v.TXNS)} transactions · select a type to open it</span><span class="timing">${o.ms.classes} ms</span>`)}</div>
        <div class="span-3">${card("TAT status by type", "timer", tatBlock || `<div class="empty">No debit-no-credit cases.</div>`, `<a class="btn ghost sm" href="#/queue?class=DEBIT_NO_CREDIT">View<i data-lucide="arrow-right"></i></a>`, `<span>${rulesLine}</span>`)}</div>
      </div>`;
    $$("[data-kpi]", app).forEach(b => b.addEventListener("click", () => go(...kpis[Number(b.dataset.kpi)].go)));
    $$("[data-step]", app).forEach(b => b.addEventListener("click", () => go(...steps[Number(b.dataset.step)].go)));
    $$("[data-class]", app).forEach(b => b.addEventListener("click", () => go("queue", { class: b.dataset.class })));
    $$("[data-bank]", app).forEach(b => {
      const open = () => go("queue", { class: "DEBIT_NO_CREDIT", bank: b.dataset.bank });
      b.addEventListener("click", open);
      b.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
    });
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
    const params = { state: p.state || "", focus: p.focus || "", bank: p.bank || "", class: p.class || "", q: p.q || "", sort: p.sort || state.meta.queue_sorts[0], page: p.page || "1", size: p.size || String(state.meta.default_page_size) };
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    const r = await call("/api/queue?" + qs);
    state.selected = new Set([...state.selected].filter(id => r.rows.some(x => x.EXC_ID === id)));
    const all = Object.values(r.tabs).reduce((a, b) => a + Number(b), 0);
    const tabs = [{ label: "All", n: all, on: !params.state && !params.focus, patch: { state: "", focus: "" } },
      ...state.meta.queue_focus.map(f => ({ label: FOCUS_LABEL[f] || title(f), n: r[f] || 0, on: params.focus === f, patch: { state: "", focus: f } })),
      ...state.meta.tat_states.map(s => ({ label: (STATE_META[s] || { label: title(s) }).label, n: r.tabs[s] || 0, on: params.state === s, patch: { state: s, focus: "" } }))];
    const pages = Math.max(1, Math.ceil(Number(r.total) / r.size));
    const csvQs = new URLSearchParams(Object.entries({ state: params.state, focus: params.focus, bank: params.bank, class: params.class, q: params.q }).filter(([, v]) => v)).toString();
    app.innerHTML = head("Work Queue", "Every open exception, plus reversed cases whose compensation is missing.",
      `<a class="btn" href="/api/compensation.csv" download><i data-lucide="badge-check"></i>Compensation register</a><a class="btn" href="/api/queue.csv${csvQs ? "?" + csvQs : ""}" download><i data-lucide="download"></i>Export this view</a>`) + `
      <section class="card">
        <div class="tabs">${tabs.map((t, i) => `<button class="tab ${t.on ? "active" : ""}" ${t.on ? 'aria-pressed="true"' : 'aria-pressed="false"'} data-tab="${i}" type="button">${esc(t.label)} <em>${fmt.n(t.n)}</em></button>`).join("")}</div>
        <p class="hint"><i data-lucide="info"></i><span>Compensation is a flat amount per day, so every accruing case costs the same to leave open. Those come first, longest wait first. Compensation already owed comes next, then cases still inside TAT, then breaks with no TAT clock.</span></p>
        <form class="toolbar" id="qf">
          <label class="search"><i data-lucide="search"></i><input name="q" value="${esc(params.q)}" placeholder="Search by UPI id, RRN or exception id" maxlength="40"></label>
          <select name="class" aria-label="Break type"><option value="">All break types</option>${r.classes.map(c => `<option value="${esc(c)}" ${c === params.class ? "selected" : ""}>${esc(classMeta(c).label)}</option>`).join("")}</select>
          <select name="sort" aria-label="Sort">${state.meta.queue_sorts.map(v => `<option value="${esc(v)}" ${v === params.sort ? "selected" : ""}>Sort: ${esc(SORT_LABEL[v] || title(v).toLowerCase())}</option>`).join("")}</select>
          <button class="btn" type="submit"><i data-lucide="filter"></i>Apply</button>
          ${params.bank ? `<span class="pill neutral">Payee bank: ${esc(params.bank)}</span>` : ""}
          ${params.q || params.class || params.bank ? `<button class="btn ghost" type="button" id="qclear">Clear</button>` : ""}
        </form>
        <div class="bulkbar" id="bulk" hidden></div>
        <div class="table-wrap"><table class="data">${queueHeader(true)}<tbody>${r.rows.map(x => queueRow(x, { select: true })).join("") || `<tr><td colspan="10"><div class="empty">Nothing matches these filters.</div></td></tr>`}</tbody></table></div>
        <div class="pager"><span>Showing ${fmt.n(r.rows.length ? (r.page - 1) * r.size + 1 : 0)}–${fmt.n((r.page - 1) * r.size + r.rows.length)} of ${fmt.n(r.total)} · <span class="timing">${r.ms} ms</span></span>
          <div class="row"><select id="psize" aria-label="Rows per page">${sizeOptions(r.size)}</select>${pager(r.page, pages)}</div></div>
      </section>`;
    const set = (patch) => go("queue", { ...params, ...patch });
    $$("[data-tab]", app).forEach(b => b.addEventListener("click", () => set({ ...tabs[Number(b.dataset.tab)].patch, page: 1 })));
    $("#qf").addEventListener("submit", e => { e.preventDefault(); const f = e.target; set({ q: f.q.value.trim(), class: f.class.value, sort: f.sort.value, page: 1 }); });
    $("#qf select[name=class]").addEventListener("change", () => $("#qf").requestSubmit());
    $("#qf select[name=sort]").addEventListener("change", () => $("#qf").requestSubmit());
    if ($("#qclear")) $("#qclear").addEventListener("click", () => set({ q: "", class: "", bank: "", page: 1 }));
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
            <div><dt>Numbers</dt><dd>Each number must appear in that turn's query results before it is shown. Open the queries to confirm what it means</dd></div>
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
    const prop = a.proposal ? (a.proposal.error ? `<span class="c-danger">Proposal refused: ${esc(a.proposal.error)}</span>` :
      `<span><i data-lucide="clipboard-check"></i><a href="#/actions?status=PROPOSED">Proposal ${esc(a.proposal.action_id)}</a>${a.proposal.duplicate ? " (already pending)" : ""} waits for approval</span>`) : "";
    return `<div class="msg-a"><div class="answer">${esc(a.answer)}</div>
      <div class="msg-meta">${a.grounded ? `<span><i data-lucide="check"></i>Every number appears in the query results</span>` : `<span class="c-danger"><i data-lucide="circle-alert"></i>Not shown as an answer: ${esc((a.ungrounded || []).join(", "))}</span>`}
        <span><i data-lucide="database"></i>${fmt.n((a.queries || []).length)} ${(a.queries || []).length === 1 ? "query" : "queries"}</span><span><i data-lucide="timer"></i>${fmt.n(a.total_ms)} ms</span>${prop}</div>${q}</div>`;
  }

  // ------------------------------------------------------------------ page: actions
  PAGES.actions = async (app, p) => {
    const status = p.status || "";
    const r = await call("/api/actions" + (status ? "?status=" + encodeURIComponent(status) : ""));
    const all = Object.values(r.counts).reduce((a, b) => a + Number(b), 0);
    setPending(r.counts.PROPOSED || 0);
    // APPROVED is transient (decide() moves it on to EXECUTED/LOGGED/FAILED), so its tab shows only when rows sit there
    const tabs = [["", "All", all], ...state.meta.action_statuses.filter(s => s !== "APPROVED" || r.counts[s])
      .map(s => [s, STATUS_TAB[s] || title(s), r.counts[s] || 0])];
    app.innerHTML = head("Proposed Actions", "Nothing changes until a named person approves. Approving runs a fixed SQL template, re-runs the reconciliation and writes the audit log.") + `
      <section class="card"><div class="tabs">${tabs.map(([s, l, n]) => `<button class="tab ${status === s ? "active" : ""}" data-st="${esc(s)}" type="button">${esc(l)} <em>${fmt.n(n)}</em></button>`).join("")}</div>
        <div style="margin-top:12px">${r.rows.map(actionCard).join("") || `<div class="empty">No actions here.</div>`}</div>
        <div class="card-foot"><span>The only action types: ${Object.entries(state.meta.action_types).map(([k, d]) => `<span title="${esc(d)}">${esc(actionMeta(k).label)}</span>`).join(", ")}</span><span class="timing">${r.ms} ms</span></div></section>`;
    $$("[data-st]", app).forEach(b => b.addEventListener("click", () => go("actions", { status: b.dataset.st })));
    $$("[data-open]", app).forEach(b => b.addEventListener("click", () => openTxn(b.dataset.open)));
    $$("[data-decide]", app).forEach(b => b.addEventListener("click", () => decide(b)));
  };
  function actionCard(a) {
    const m = actionMeta(a.ACTION_TYPE);
    const proposed = a.STATUS === "PROPOSED";
    const own = proposed && state.meta.maker_checker && who.get() && String(a.CREATED_BY).trim().toLowerCase() === (state.meta.analyst_prefix + who.get()).trim().toLowerCase();
    const impact = proposed && isNum(a.POST_RS) ? `<div class="impact"><i data-lucide="corner-down-right"></i>Approving posts a ${fmt.rs(a.POST_RS)} credit${Number(a.NEW_ACCRUAL_RS) > 0 ? ` and avoids ${fmt.rs(a.NEW_ACCRUAL_RS)} tomorrow` : ""}</div>` : "";
    const target = a.ACTION_TYPE === "CHASE_SETTLEMENT_FILE" ? `<span class="mono">${esc(a.TARGET_REF)}</span>` : `<button class="btn ghost sm mono" data-open="${esc(a.TARGET_REF)}" type="button">${esc(a.TARGET_REF)}</button>`;
    return `<div class="action-card"><div>
        <h4><i data-lucide="${m.icon}"></i>${esc(m.label)} ${target} ${pill(title(a.STATUS), STATUS_TONE[a.STATUS] || "neutral")}</h4>
        <p class="wrap">${esc(a.RATIONALE || "")}</p>${impact}
        ${own ? `<div class="impact muted"><i data-lucide="users"></i>You proposed this, so a second person must approve it. You can still reject it.</div>` : ""}
        <div class="meta"><span>Proposed by ${esc(a.CREATED_BY)} · ${fmt.dt(a.CREATED)}</span>${a.DECIDED_BY ? `<span>Decided by ${esc(a.DECIDED_BY)} · ${fmt.dt(a.DECIDED)}</span>` : ""}<span class="mono">${esc(a.ACTION_ID)}</span></div></div>
      <div class="side">${a.STATUS === "PROPOSED" ? `<button class="btn" data-decide="reject" data-id="${esc(a.ACTION_ID)}" type="button"><i data-lucide="x"></i>Reject</button>
        <button class="btn primary" data-decide="approve" data-id="${esc(a.ACTION_ID)}" type="button" ${own ? "disabled" : ""}><i data-lucide="check"></i>Approve</button>` : ""}</div></div>`;
  }
  async function decide(btn) {
    const user = who.require();
    if (!user) return;
    const approve = btn.dataset.decide === "approve";
    if (!btn.dataset.armed) {   // two-step confirmation, no browser dialog
      btn.dataset.armed = "1";
      btn.innerHTML = `<i data-lucide="${approve ? "check" : "x"}"></i>Confirm ${approve ? "approval" : "rejection"} as ${esc(user)}`;
      icons(btn);
      setTimeout(() => { if (btn.isConnected && btn.dataset.armed) { delete btn.dataset.armed; route(); } }, 6000);
      return;
    }
    const side = btn.closest(".side");
    $$("button", side).forEach(b => (b.disabled = true));
    btn.innerHTML = approve ? "Executing and re-running the reconciliation…" : "Rejecting…";
    try {
      const r = await call(`/api/actions/${encodeURIComponent(btn.dataset.id)}/${approve ? "approve" : "reject"}`, { user });
      if (r.status === "FAILED") toast(`Execution failed and was logged: ${esc(r.error || "")}`, true);
      else if (r.error) toast(esc(r.error), true);
      else if (approve && r.before && r.after && r.status === "EXECUTED") toast(`Executed. Added tomorrow across the queue: ${fmt.rs(r.before.new_accrual_24h_rs)} → ${fmt.rs(r.after.new_accrual_24h_rs)} (${fmt.n(Math.round(r.total_ms / 1000))} s).`);
      else toast(`${title(r.status)}: ${esc(btn.dataset.id)}`);
    } catch (e) { toast(esc(e.message), true); }
    loadShell(); route();
  }

  // ------------------------------------------------------------------ page: audit
  PAGES.audit = async (app) => {
    const r = await call("/api/audit");
    const eff = row => {
      try {
        const b = JSON.parse(row.BEFORE_JSON || "{}"), a = JSON.parse(row.AFTER_JSON || "{}");
        const t = a.target && b.target ? `<div class="delta">Case ${esc(title(b.target.STATUS))}<i data-lucide="arrow-right"></i>${esc(title(a.target.STATUS))}${a.target.COMP_STATUS ? ` · compensation ${esc(title(a.target.COMP_STATUS))}` : ""}</div>` : "";
        return `<div class="delta">${fmt.rs(b.exposure_next_24h_rs)}<i data-lucide="arrow-right"></i>${fmt.rs(a.exposure_next_24h_rs)} owed tomorrow</div>${t}${a.error ? `<div class="c-danger">${esc(a.error)}</div>` : ""}`;
      } catch (e) { return "–"; }
    };
    app.innerHTML = head("Audit Log", "Every executed action: who approved it, when, the exact SQL that ran, and the numbers before and after.") + `
      <section class="card"><div class="table-wrap"><table class="data"><thead><tr><th>Executed</th><th>Action</th><th>Target</th><th>Proposed by</th><th>Approved by</th><th>Outcome</th><th>Effect</th></tr></thead>
        <tbody>${r.rows.map(x => `<tr><td>${fmt.dt(x.EXECUTED)}</td>
          <td><b>${esc(actionMeta(x.ACTION_TYPE).label)}</b><div class="mono subtle">${esc(x.ACTION_ID)}</div></td>
          <td class="mono wrap">${esc(x.TARGET_REF)}</td><td>${esc(x.CREATED_BY || "–")}</td><td>${esc(x.EXECUTED_BY)}</td>
          <td>${pill(title(x.OUTCOME), STATUS_TONE[x.OUTCOME] || "neutral")}</td>
          <td>${eff(x)}<details class="sql"><summary><span>Executed SQL</span><i data-lucide="chevrons-up-down"></i></summary><pre>${esc(x.EXECUTED_SQL)}</pre></details></td></tr>`).join("")
          || `<tr><td colspan="7"><div class="empty">Nothing has been executed yet.</div></td></tr>`}</tbody></table></div>
        <div class="card-foot"><span>The audit tables are append-only; a demo reset with <span class="mono">--reset-audit</span> is the only way they are emptied</span><span class="timing">${r.ms} ms</span></div></section>`;
  };

  // ------------------------------------------------------------------ page: data sources
  PAGES.sources = async (app) => {
    const [s, o] = await Promise.all([call("/api/sources"), call("/api/overview")]);
    setContext(o);
    const META = { SWITCH_LOG: ["UPI switch log", "arrow-left-right", "var(--info-soft);color:var(--info)"],
      NPCI_SETTLEMENT: ["NPCI settlement file", "landmark", "var(--brand-soft);color:var(--brand)"],
      CBS_LEDGER: ["Core-banking ledger", "book-open", "var(--violet-soft);color:var(--violet)"],
      SETTLEMENT_FILE_LOG: ["Settlement file arrivals", "file-clock", "var(--warn-soft);color:var(--warn)"] };
    const dates = [...new Set(s.files.map(f => f.SETTLEMENT_DT))];
    const cycles = [...new Set(s.files.map(f => f.CYCLE_NO))].sort((a, b) => a - b);
    const STATUS_LABEL = { ON_TIME: "On time", LATE: "Late", NOT_ARRIVED: "Missing", NOT_DUE: "Not due" };
    const cell = f => f ? `<div class="filecell f-${esc(f.FILE_STATUS)}" title="${esc(STATUS_LABEL[f.FILE_STATUS] || f.FILE_STATUS)} · expected ${esc(f.EXPECTED)}${f.ARRIVED ? " · arrived " + esc(f.ARRIVED) : ""} · ${fmt.n(f.RECORD_COUNT)} records">${esc(STATUS_LABEL[f.FILE_STATUS] || f.FILE_STATUS)}</div>` : "<div></div>";
    const late = s.files.filter(f => f.FILE_STATUS !== "ON_TIME" && f.FILE_STATUS !== "NOT_DUE");
    const h = state.health || await call("/api/health");
    app.innerHTML = head("Data Sources", "The three synthetic sources the reconciliation reads, as loaded into Exasol, and the settlement files' arrival record.") + `
      <div class="grid">${s.tables.map(t => { const m = META[t.TABLE] || [t.TABLE, "table-2", "var(--neutral-soft);color:var(--text)"]; return `<div class="span-3"><section class="card source-card">
          <div class="top"><span class="ic" style="background:${m[2]}"><i data-lucide="${m[1]}"></i></span><div><h4>${esc(m[0])}</h4><div class="mono subtle">RAW.${esc(t.TABLE)}</div></div></div>
          <dl><div><dt>Rows</dt><dd>${fmt.n(t.ROWS)}</dd></div><div><dt>Columns</dt><dd>${fmt.n(t.COLS)}</dd></div><div><dt>Load time</dt><dd>${t.LOAD_MS !== null && t.LOAD_MS !== undefined ? fmt.n(Math.round(Number(t.LOAD_MS) / 100) / 10) + " s" : "–"}</dd></div></dl>
          <div class="muted" style="font-size:12.5px">Last loaded ${t.LOADED ? fmt.dt(t.LOADED) : "– (no load logged)"}</div></section></div>`; }).join("")}
        <div class="span-8">${card("Settlement files by day and cycle", "file-clock", `<div class="filegrid" style="--cycles:${cycles.length}">
            <div></div>${cycles.map(c => `<div class="h">Cycle ${fmt.n(c)}</div>`).join("")}
            ${dates.map(d => `<div class="d">${fmt.dayLong(d)}</div>${cycles.map(c => cell(s.files.find(f => f.SETTLEMENT_DT === d && f.CYCLE_NO === c))).join("")}`).join("")}</div>
            <div class="legend" style="margin-top:12px">${Object.entries(STATUS_LABEL).map(([k, l]) => `<span><i class="sw f-${k}"></i>${l}</span>`).join("")}</div>`, "",
          `<span>${late.length ? late.map(f => `${fmt.dayLong(f.SETTLEMENT_DT)} cycle ${fmt.n(f.CYCLE_NO)}: ${esc(STATUS_LABEL[f.FILE_STATUS])}, ${fmt.n(f.MINUTES_AFTER_EXPECTED)} min after expected`).join(" · ") : "Every due file arrived on time"} · late means more than ${fmt.n(s.grace_minutes)} min after expected</span><span class="timing">${s.ms} ms</span>`)}</div>
        <div class="span-4" style="display:grid;gap:16px;align-content:start">
          ${card("TAT rules in force", "scale", `<table class="data"><thead><tr><th>Type</th><th class="n">TAT</th><th class="n">Beyond TAT</th><th>Source</th></tr></thead><tbody>
            ${o.rules.map(r => `<tr><td>${esc(r.TXN_TYPE)}</td><td class="n">T+${fmt.n(r.TAT_DAYS)}</td><td class="n">${fmt.rs(r.RS_PER_DAY)}/day</td><td class="mono">${esc(r.FACT_ID)}</td></tr>`).join("")}</tbody></table>`, "",
            `<span>Loaded from facts.yaml into RECON.TAT_RULES; never typed into SQL</span>`)}
          ${card("Connection", "server", `<div class="kv"><div><dt>Database</dt><dd>Exasol ${esc(h.version)}</dd></div><div><dt>Host</dt><dd class="mono">${esc(h.host)}</dd></div>
            <div><dt>Instance label</dt><dd>${esc(h.host_label)}</dd></div><div><dt>Assistant</dt><dd>${esc(h.agent_ready ? h.agent_mode : (h.agent_error || "starting"))}</dd></div></div>`)}
        </div></div>`;
  };

  // ------------------------------------------------------------------ page: reports
  PAGES.reports = async (app, p) => {
    const [list, runs] = await Promise.all([call("/api/reports"), call("/api/runs")]);
    const name = p.name || (list.items.find(i => i.name.startsWith("verifier_")) || list.items[0] || {}).name;
    const doc = name ? await call("/api/report?name=" + encodeURIComponent(name)) : null;
    app.innerHTML = head("Reports", "Saved verification reports and measured run timings, straight from the repository's reports folder.") + `
      <div class="grid"><div class="span-4" style="display:grid;gap:16px;align-content:start"><section class="card"><div class="card-head"><h3><span class="hicon"><i data-lucide="file-text"></i></span>Reports</h3></div>
          <div class="report-list" style="margin-top:10px">${list.items.map(i => `<button class="${i.name === name ? "active" : ""}" data-name="${esc(i.name)}" type="button"><i data-lucide="${i.name.endsWith(".csv") ? "table-2" : "file-text"}"></i><span><span class="wrap">${esc(i.name)}</span><small>${fmt.dt(i.modified)} · ${fmt.n(Math.ceil(i.bytes / 1024))} KB</small></span></button>`).join("")}</div></section>
          ${card("Reconciliation runs", "timer", `<div class="table-wrap"><table class="data"><thead><tr><th>Started</th><th class="n">Recon</th><th class="n">Load</th></tr></thead><tbody>
            ${runs.runs.map(r => `<tr><td>${fmt.dt(r.STARTED)}</td><td class="n">${Number(r.RECON_MS) ? fmt.n(Math.round(Number(r.RECON_MS) / 100) / 10) + " s" : "–"}</td><td class="n">${Number(r.LOAD_MS) ? fmt.n(Math.round(Number(r.LOAD_MS) / 100) / 10) + " s" : "–"}</td></tr>`).join("")}</tbody></table></div>`, "", `<span>From RECON.RUN_LOG, measured with a timer around each Exasol call</span>`)}</div>
        <div class="span-8"><section class="card"><div class="card-head"><h3><span class="hicon"><i data-lucide="file-search"></i></span><span class="mono">${esc(name || "No reports")}</span></h3></div>
          <div class="card-body md">${doc ? renderDoc(doc) : `<div class="empty">No reports saved yet.</div>`}</div></section></div></div>`;
    $$("[data-name]", app).forEach(b => b.addEventListener("click", () => go("reports", { name: b.dataset.name })));
  };
  function renderDoc(doc) {
    if (doc.name.endsWith(".csv")) {
      const rows = doc.text.trim().split(/\r?\n/).map(l => l.split(","));
      return `<div class="table-wrap" style="max-height:640px"><table class="data"><thead><tr>${rows[0].map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(1).map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    // minimal, escape-first Markdown: headings, tables, fenced code, bold, paragraphs
    const out = [], lines = doc.text.split(/\r?\n/);
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, '<span class="mono">$1</span>');
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (l.startsWith("```")) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); out.push(`<pre class="code">${esc(buf.join("\n"))}</pre>`); continue; }
      const hm = l.match(/^(#{1,3})\s+(.*)/);
      if (hm) { out.push(`<h${hm[1].length}>${inline(hm[2])}</h${hm[1].length}>`); continue; }
      if (l.trim().startsWith("|")) {
        const rows = []; while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]); i--;
        const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
        const body = rows.filter((r, k) => k !== 1 || !/^[\s|:-]+$/.test(r));
        out.push(`<div class="table-wrap"><table class="data"><thead><tr>${cells(body[0]).map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.slice(1).map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (l.trim()) out.push(`<p>${inline(l)}</p>`);
    }
    return out.join("");
  }

  // ------------------------------------------------------------------ transaction drawer
  // One plain sentence on what this case needs, built from the same live values the drawer shows below it.
  function nextStep(e, pen, qr) {
    if (!qr) return null;
    const partial = Number(e.REVERSED_RS) > 0 && e.STATUS === "OPEN" ? ` ${fmt.rs(e.REVERSED_RS)} of ${fmt.rs(e.DEBIT_TOTAL_RS)} has been reversed; the rest is still due.` : "";
    const deadline = pen ? fmt.dayLong(pen.DEADLINE_DT) : "";
    if (qr.TAT_STATE === "OVERDUE") return ["danger", `Reverse now. This case is ${clockText(pen.DAYS_TO_DEADLINE).toLowerCase()}: ${fmt.rs(pen.PENALTY_RS)} has accrued and ${fmt.rs(pen.NEW_ACCRUAL_RS)} more is added tomorrow.${partial}`];
    if (qr.TAT_STATE === "AT_RISK") return ["warn", `Reverse today. The deadline is ${deadline}; if it stays open, ${fmt.rs(pen.NEW_ACCRUAL_RS)} is added tomorrow.${partial}`];
    if (qr.TAT_STATE === "WITHIN_TAT") return ["info", `${clockText(pen.DAYS_TO_DEADLINE)}. Reversal is due by ${deadline}.${partial}`];
    if (qr.TAT_STATE === "COMPENSATION_DUE") return ["violet", `Reversed on ${fmt.dayLong(e.REVERSAL_DT)}, after the deadline. ${fmt.rs(pen.COMP_GAP_RS)} of compensation is still owed, without waiting for a complaint.`];
    return ["neutral", "TAT Guard prices no TAT penalty for this break type. It still needs a person to review it."];
  }
  const copyBtn = (v, label) => v ? `<button class="copy" data-copy="${esc(v)}" type="button" aria-label="Copy ${esc(label)}" title="Copy ${esc(label)}"><i data-lucide="copy"></i></button>` : "";
  async function openTxn(id) {
    const d = $("#drawer"), body = $("#drawer-body");
    if (!d.classList.contains("open")) state.lastFocus = document.activeElement;
    $("#drawer-title").textContent = id;
    body.innerHTML = `<div class="skeleton" role="status" aria-label="Loading"><i></i><i></i></div>`;
    d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
    $("#drawer-close").focus();
    try {
      const t = await call("/api/txn?id=" + encodeURIComponent(id));
      const e = t.exception || {}, s = t.state || {}, pen = t.penalty, qr = t.queue;
      $("#drawer-title").textContent = s.UPI_TXN_ID || e.UPI_TXN_ID || e.CBS_ENTRY_ID || id;
      const act = qr && !t.actions.some(a => a.STATUS === "PROPOSED") ? qr.PROPOSE_ACTION : null;
      const sw = t.switch.map(r => `<div class="box"><b>${esc(title(r.STATUS))}</b> · ${fmt.rs(r.AMOUNT_RS)} · response ${esc(r.RESP_CODE)} · channel ${esc(r.CHANNEL)}<div class="subtle">${fmt.dt(r.TXN_TIME)} · RRN <span class="mono">${esc(r.RRN)}</span>${r.UPI_TXN_ID ? "" : " · no UPI id logged"}</div></div>`).join("") || `<div class="box">No switch record.</div>`;
      const np = t.npci.map(r => `<div class="box"><b>${esc(title(r.STATUS))}</b> · ${fmt.rs(r.AMOUNT_RS)} · response ${esc(r.RESP_CODE)} · payee ${esc(r.PAYEE_BANK)}<div class="subtle">Settlement ${fmt.dayLong(r.SETTLEMENT_DT)}, cycle ${fmt.n(r.CYCLE_NO)}</div></div>`).join("")
        || `<div class="box">No NPCI record yet.${s.FILE_EXPECTED ? ` The settlement file for ${fmt.dayLong(s.FILE_SETTLEMENT_DT)} cycle ${fmt.n(s.FILE_CYCLE_NO)} was expected ${fmt.dt(s.FILE_EXPECTED)} and ${s.FILE_ARRIVED ? "arrived " + fmt.dt(s.FILE_ARRIVED) : "has not arrived"}.` : ""}</div>`;
      const cb = t.cbs.map(r => `<div class="box"><b>${esc(r.DR_CR === "DR" ? (r.KIND === "DEBIT" ? "Debit" : "Debit · " + title(r.KIND)) : "Credit · " + title(r.KIND))}</b> · ${fmt.rs(r.AMOUNT_RS)}${r.MATCH_PASS ? ` · matched in pass ${fmt.n(r.MATCH_PASS)}` : ""}<div class="subtle">${fmt.dt(r.POST_TIME)} · <span class="mono">${esc(r.CBS_ENTRY_ID)}</span></div><div class="mono wrap" style="margin-top:4px">${esc(r.NARRATION)}</div></div>`).join("") || `<div class="box">No core-banking entry.</div>`;
      const next = nextStep(e, pen, qr);
      body.innerHTML = `
        ${next ? `<div class="next ${next[0]}">${esc(next[1])}</div>` : ""}
        <div class="row" style="flex-wrap:wrap">${e.CLASS ? classTag(e.CLASS) : pill("Reconciled", "brand")}${qr ? statePill(qr.TAT_STATE) : ""}${e.STATUS ? pill(title(e.STATUS), "neutral") : ""}${qr ? `<span class="muted">Queue rank ${fmt.n(qr.QUEUE_RANK)}</span>` : ""}</div>
        <dl class="kv"><div><dt>Amount</dt><dd>${fmt.rs(s.AMOUNT_RS || e.AMOUNT_RS)}</dd></div><div><dt>Type</dt><dd>${esc(s.TXN_TYPE || e.TXN_TYPE || "–")}</dd></div>
          <div><dt>Transaction time</dt><dd>${fmt.dt(s.TXN_TIME || e.TXN_TIME)}</dd></div><div><dt>RRN</dt><dd class="mono">${esc(s.RRN || e.RRN || "–")}${copyBtn(s.RRN || e.RRN, "RRN")}</dd></div>
          <div><dt>Payee bank</dt><dd>${esc(s.PAYEE_BANK || e.BANK || "–")}</dd></div><div><dt>Exception id</dt><dd class="mono">${esc(e.EXC_ID || "–")}${copyBtn(e.EXC_ID, "exception id")}</dd></div></dl>
        ${pen ? `<div><p class="section-title">TAT clock</p><dl class="kv">
          <div><dt>Rule</dt><dd>${esc(pen.CASE_NAME)} · T+${fmt.n(pen.TAT_DAYS)}</dd></div><div><dt>Deadline</dt><dd>${fmt.dayLong(pen.DEADLINE_DT)}</dd></div>
          <div><dt>Days beyond TAT</dt><dd>${fmt.n(pen.PENALTY_DAYS)}</dd></div><div><dt>Accrued</dt><dd>${fmt.rs(pen.PENALTY_RS)}</dd></div>
          <div><dt>Owed tomorrow</dt><dd>${fmt.rs(pen.OWED_TOMORROW_RS)}</dd></div><div><dt>Compensation</dt><dd>${esc(title(pen.COMP_STATUS))}${Number(pen.COMP_GAP_RS) > 0 ? ` · gap ${fmt.rs(pen.COMP_GAP_RS)}` : ""}</dd></div></dl></div>` : ""}
        <div><p class="section-title">What each system recorded</p><div class="timeline">
          <div class="tl"><span class="ic"><i data-lucide="arrow-left-right"></i></span><div><h5>Bank's UPI switch</h5>${sw}</div></div>
          <div class="tl"><span class="ic"><i data-lucide="landmark"></i></span><div><h5>NPCI settlement</h5>${np}</div></div>
          <div class="tl"><span class="ic"><i data-lucide="book-open"></i></span><div><h5>Core-banking ledger</h5>${cb}</div></div></div></div>
        ${t.actions.length ? `<div><p class="section-title">Actions</p>${t.actions.map(a => `<div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line-2)"><span>${esc(actionMeta(a.ACTION_TYPE).label)} · ${esc(a.CREATED_BY)}</span>${pill(title(a.STATUS), STATUS_TONE[a.STATUS] || "neutral")}</div>`).join("")}</div>` : ""}
        ${act ? `<div class="row"><button class="btn primary" id="drawer-propose" type="button"><i data-lucide="${actionMeta(act).icon}"></i>${esc(actionMeta(act).cta)}</button><span class="muted">A named person approves it on the Actions page.</span></div>` : ""}`;
      icons(body);
      $$("[data-copy]", body).forEach(b => b.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(b.dataset.copy); toast("Copied."); } catch (err) { toast("Copy is not available in this browser.", true); }
      }));
      if ($("#drawer-propose")) $("#drawer-propose").addEventListener("click", async () => { if (await propose(act, [e.EXC_ID])) { openTxn(id); route(); } });
    } catch (err) { body.innerHTML = `<div class="error-box">${esc(err.message)}</div>`; }
  }
  function closeDrawer() {
    if (!$("#drawer").classList.contains("open")) return;
    $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true;
    if (state.lastFocus && state.lastFocus.isConnected) state.lastFocus.focus();
    const { page, params } = parseHash();
    if (params.open) { delete params.open; history.replaceState(null, "", `#/${page}${Object.keys(params).length ? "?" + new URLSearchParams(params) : ""}`); }
  }
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  // ------------------------------------------------------------------ boot
  who.render();
  icons();
  loadShell();
  call("/api/overview").then(setContext).catch(() => { /* shown per page */ });
  // pages build their menus from /api/meta (no database needed), so it loads before the first render
  call("/api/meta").then(m => { state.meta = m; route(); })
    .catch(e => { $("#app").innerHTML = `<div class="error-box">Cannot reach the TAT Guard server: ${esc(e.message)}</div>`; });
})();
