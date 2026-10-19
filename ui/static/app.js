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