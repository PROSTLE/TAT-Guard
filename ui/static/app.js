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
    DEBIT_NO_CREDIT: { label: "Debit, no credit", color: "var(--c-dnc)" },
    LATE_FILE: { label: "Late settlement file", color: "var(--c-late)" },
    AMOUNT_MISMATCH: { label: "Amount mismatch", color: "var(--c-amt)" },
    NPCI_SUCCESS_NO_CBS: { label: "NPCI success, no CBS debit", color: "var(--c-npci)" },
    DUPLICATE_POSTING: { label: "Duplicate posting", color: "var(--c-dup)" },
    NPCI_MISSING: { label: "Missing in NPCI", color: "var(--c-miss)" },
    UNMATCHED_CBS_DEBIT: { label: "Unmatched CBS debit", color: "var(--c-orphan)" },
  };
  const classMeta = c => CLASS_META[c] || { label: title(c), color: "var(--c-orphan)" };
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
  const errorBox = msg => `<div class="error-box"><div>${esc(msg)}</div><div class="row"><a class="btn sm" href="#/connect">Connect and import</a><button class="btn sm" type="button" data-retry><i data-lucide="refresh-cw"></i>Try again</button></div></div>`;
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
      $("#data-chip span").textContent = "No connection";
      $("#offline").hidden = false;
      $("#conn").classList.add("bad");
      $("#conn").innerHTML = `<i data-lucide="server-off"></i><span>Database unreachable</span>`;
      icons($("#conn"));
    }
  }
  function setPending(n) {
    const el = $("#nav-pending");
    el.hidden = !(Number(n) > 0);
    el.textContent = fmt.n(n);
    el.setAttribute("aria-label", `${fmt.n(n)} actions waiting for approval`);
  }
  function setContext(o) {
    const chip = $("#data-chip"), sample = o.dataset.source === "sample";
    chip.classList.toggle("imported", !sample);
    chip.querySelector("span").textContent = sample ? "Synthetic data" : o.dataset.source === "none" ? o.dataset.name : `Imported: ${o.dataset.name}`;
    chip.title = `${o.dataset.name}. Layouts are stand-ins, not real NPCI, switch or CBS formats. Select to see where this data comes from.`;
    $("#ctx-window span").textContent = `Cut-off ${fmt.dt(o.as_of)}`;
    $("#ctx-window").title = `Transactions ${fmt.day(o.volume.FIRST_DT)} – ${fmt.dayLong(o.volume.LAST_DT)}, cut-off ${fmt.dt(o.as_of)}`;
    const took = isNum(o.recon_ms) ? ` · ${fmt.n(Math.round(Number(o.recon_ms) / 100) / 10)} s` : "";
    $("#ctx-run span").textContent = o.last_recon ? `Last run ${fmt.dt(o.last_recon)}${took}` : "No run logged";
    setPending(o.pending);
  }

  // ------------------------------------------------------------------ router
  const state = { meta: null, health: null, thread: [], selected: new Set() };
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, qs] = h.split("?");
    return { page: path || "home", params: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function href(page, params = {}) {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)).toString();
    return `#/${page}${qs ? "?" + qs : ""}`;
  }
  function go(page, params = {}) { location.hash = href(page, params); }
  const PAGES = {};
  async function route() {
    if (!state.meta) return;   // boot calls route() once /api/meta has loaded
    const { page, params } = parseHash();
    const render = PAGES[page] || PAGES.home;
    document.body.dataset.page = PAGES[page] ? page : "home";
    window.scrollTo(0, 0);
    $$("#nav a").forEach(a => {
      const on = a.dataset.page === (PAGES[page] ? page : "home");
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
    tour.paint();
  }
  window.addEventListener("hashchange", route);
  $("#refresh").addEventListener("click", () => { loadShell(); route(); });
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "dark";
    if (dark) document.documentElement.dataset.theme = "dark"; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("tg_theme", dark ? "dark" : "light"); } catch (e) { /* storage unavailable */ }
  });
  $("#find").addEventListener("submit", e => { e.preventDefault(); const v = e.target.q.value.trim(); if (v) { e.target.q.value = ""; go("transactions", { q: v }); } });

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
  function spark(values) {
    const vals = values.map(Number).filter(v => !Number.isNaN(v));
    if (vals.length < 2) return "";
    const W = 400, H = 62, max = Math.max(...vals), min = Math.min(...vals);
    const pts = vals.map((v, i) => [i * W / (vals.length - 1), H - 3 - (max === min ? (H - 6) / 2 : (v - min) / (max - min) * (H - 6))]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    return `<svg class="cost-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${d} L${W} ${H} L0 ${H} Z" fill="currentColor" opacity=".16"></path>
      <path d="${d}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"></path></svg>`;
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
      <path d="${area}" style="fill:var(--brand)" opacity=".08"></path>
      <path d="${solid("ACCRUED_RS")}" fill="none" style="stroke:var(--series-2)" stroke-width="2"></path>
      <path d="${proj("ACCRUED_RS")}" fill="none" style="stroke:var(--series-2)" stroke-width="2" stroke-dasharray="5 5"></path>
      <path d="${solid("OPEN_RS")}" fill="none" style="stroke:var(--brand)" stroke-width="2.4"></path>
      <path d="${proj("OPEN_RS")}" fill="none" style="stroke:var(--brand)" stroke-width="2.4" stroke-dasharray="5 5"></path>
      ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.OPEN_RS)}" r="4" style="fill:var(${Number(p.PROJECTED) ? "--surface" : "--brand"});stroke:var(--surface)" stroke-width="2"></circle>`).join("")}
      <line id="trend-guide" x1="0" x2="0" y1="${T}" y2="${H - B}" style="stroke:var(--line-3)" stroke-dasharray="3 3" visibility="hidden"></line>
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
      <td><div class="mono">${esc(r.UPI_TXN_ID || r.EXC_ID)}</div><div class="cell-sub">${esc(r.TXN_TYPE || "–")} · ${fmt.dt(r.TXN_TIME)}</div></td>
      <td class="n">${fmt.rs(r.AMOUNT_RS)}</td>
      <td>${classTag(r.CLASS)}</td>
      <td>${statePill(r.TAT_STATE)}${clock ? `<div class="cell-sub">${esc(clock)}</div>` : ""}</td>
      <td class="n">${Number(r.NEW_ACCRUAL_RS) > 0 ? `<b class="c-danger">+${fmt.rs(r.NEW_ACCRUAL_RS)}</b>` : `<span class="subtle">–</span>`}${Number(r.ACCRUED_RS) > 0 ? `<div class="cell-sub">${fmt.rs(r.ACCRUED_RS)} so far</div>` : ""}</td>
      <td onclick="event.stopPropagation()">${actionCell}</td></tr>`;
  }
  const queueHeader = (select) => `<thead><tr>${select ? `<th style="width:34px"><input type="checkbox" id="sel-all" aria-label="Select all eligible rows"></th>` : ""}
      <th class="n">#</th><th>Transaction</th><th class="n">Amount</th><th>Break type</th><th>Clock</th><th class="n" title="What this case adds to the compensation bill by tomorrow if it stays open">Adds tomorrow</th><th>Action</th></tr></thead>`;

  async function propose(kind, refs) {
    const user = who.require();
    if (!user) return false;
    try {
      const r = await call("/api/propose", { action_type: kind, targets: refs, user });
      const ok = r.results.filter(x => !x.error), bad = r.results.filter(x => x.error);
      if (ok.length) toast(`${ok.length} ${ok.length === 1 ? "proposal" : "proposals"} waiting for approval. <a href="#/actions?status=PROPOSED">Review in Approvals</a>`);
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

  // ------------------------------------------------------------------ illustrations (decoration only, they carry no data)
  const face = (x, y, s = 1) => `<g transform="translate(${x} ${y}) scale(${s})"><circle cx="-13" cy="0" r="3.4" fill="var(--il-ink)"></circle><circle cx="13" cy="0" r="3.4" fill="var(--il-ink)"></circle>
    <circle cx="-22" cy="8" r="4.4" fill="var(--il-cheek)" opacity=".8"></circle><circle cx="22" cy="8" r="4.4" fill="var(--il-cheek)" opacity=".8"></circle>
    <path d="M-7 7 Q0 15 7 7" fill="none" stroke="var(--il-ink)" stroke-width="2.6" stroke-linecap="round"></path></g>`;
  const INK = `stroke="var(--il-ink)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"`;
  const SHIELD = "M180 62 C204 82 234 92 264 94 C266 158 250 232 180 276 C110 232 94 158 96 94 C126 92 156 82 180 62 Z";
  const sourceTile = (x, y, label, fill) => `<g transform="translate(${x} ${y})"><rect x="-31" y="-18" width="62" height="36" rx="10" fill="${fill}" ${INK}></rect>
    <text x="0" y="5.5" text-anchor="middle" style="font:700 14px var(--display);fill:var(--il-ink)">${label}</text></g>`;
  const ticks = Array.from({ length: 12 }, (_, i) => { const a = i * Math.PI / 6, c = Math.cos(a), s = Math.sin(a);
    return `<line x1="${(180 + 144 * s).toFixed(1)}" y1="${(166 - 144 * c).toFixed(1)}" x2="${(180 + 154 * s).toFixed(1)}" y2="${(166 - 154 * c).toFixed(1)}" stroke="var(--il-ring)" stroke-width="3" stroke-linecap="round"></line>`; }).join("");
  const MASCOT = `<svg class="mascot" viewBox="0 0 360 330" aria-hidden="true">
    <ellipse cx="180" cy="312" rx="112" ry="10" fill="var(--il-shadow)"></ellipse>
    <circle cx="180" cy="166" r="149" fill="none" stroke="var(--il-ring)" stroke-width="2" stroke-dasharray="2 10" stroke-linecap="round"></circle>${ticks}
    <path d="M180 17 A149 149 0 0 1 322 121" fill="none" stroke="var(--il-gold)" stroke-width="5" stroke-linecap="round"></path>
    <path d="M152 262 L146 298 M208 262 L214 298" fill="none" stroke="var(--il-paper)" stroke-width="7" stroke-linecap="round"></path>
    <ellipse cx="141" cy="301" rx="15" ry="7" fill="var(--il-paper)" ${INK}></ellipse><ellipse cx="219" cy="301" rx="15" ry="7" fill="var(--il-paper)" ${INK}></ellipse>
    <path d="M100 168 Q72 158 62 122" fill="none" stroke="var(--il-paper)" stroke-width="7" stroke-linecap="round"></path><circle cx="60" cy="114" r="10" fill="var(--il-paper)" ${INK}></circle>
    <path d="M258 186 Q280 200 288 222" fill="none" stroke="var(--il-paper)" stroke-width="7" stroke-linecap="round"></path>
    <path d="${SHIELD}" fill="var(--il-paper)" ${INK} stroke-width="5"></path>
    <path d="M180 76 C202 94 230 102 254 104 C254 124 252 142 248 160 L112 160 C108 142 106 124 106 104 C130 102 158 94 180 76 Z" fill="var(--il-mint)" opacity=".85"></path>
    ${face(180, 186, 1.5)}
    <circle cx="180" cy="125" r="21" fill="var(--il-paper)" ${INK}></circle><path d="M180 112 L180 125 L190 131" fill="none" ${INK}></path>
    <circle cx="298" cy="246" r="33" fill="var(--il-gold)" ${INK}></circle><text x="298" y="258" text-anchor="middle" style="font:700 36px var(--display);fill:var(--il-ink)">₹</text>
    ${sourceTile(54, 58, "UPI", "var(--il-blue)")}${sourceTile(312, 42, "NPCI", "var(--il-mint)")}${sourceTile(44, 232, "CBS", "var(--il-gold)")}
  </svg>`;
  const mascotMini = `<svg class="mascot-mini" viewBox="84 50 192 240" aria-hidden="true"><path d="${SHIELD}" fill="var(--il-paper)" ${INK} stroke-width="5"></path>
    <path d="M180 76 C202 94 230 102 254 104 C254 124 252 142 248 160 L112 160 C108 142 106 124 106 104 C130 102 158 94 180 76 Z" fill="var(--il-mint)" opacity=".85"></path>${face(180, 186, 1.5)}
    <circle cx="180" cy="125" r="21" fill="var(--il-paper)" ${INK}></circle><path d="M180 112 L180 125 L190 131" fill="none" ${INK}></path></svg>`;
  const ART = {
    today: `<svg viewBox="0 0 280 130" aria-hidden="true"><ellipse cx="140" cy="120" rx="64" ry="5" fill="var(--il-shadow)" opacity=".5"></ellipse>
      <circle cx="140" cy="66" r="48" fill="var(--il-paper)" ${INK}></circle><path d="M140 18 A48 48 0 0 1 188 66 L140 66 Z" fill="var(--il-gold)" opacity=".9"></path><circle cx="140" cy="66" r="48" fill="none" ${INK}></circle>
      ${face(140, 74, .95)}<path d="M104 26 L92 16 M176 26 L188 16" fill="none" stroke="var(--il-line)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"></path>
      <circle cx="214" cy="42" r="15" fill="var(--il-gold)" ${INK}></circle><text x="214" y="48.5" text-anchor="middle" style="font:700 17px var(--display);fill:var(--il-ink)">₹</text></svg>`,
    queue: `<svg viewBox="0 0 280 130" aria-hidden="true">
      <rect x="72" y="16" width="150" height="28" rx="9" fill="var(--il-paper)" ${INK}></rect><circle cx="90" cy="30" r="9" fill="var(--il-red)" ${INK} stroke-width="3"></circle><path d="M108 30 H196" ${INK}></path>
      <rect x="72" y="52" width="150" height="28" rx="9" fill="var(--il-paper)" ${INK}></rect><circle cx="90" cy="66" r="9" fill="var(--il-gold)" ${INK} stroke-width="3"></circle><path d="M108 66 H176" ${INK}></path>
      <rect x="72" y="88" width="150" height="28" rx="9" fill="var(--il-paper)" ${INK}></rect><circle cx="90" cy="102" r="9" fill="var(--il-mint)" ${INK} stroke-width="3"></circle><path d="M108 102 H158" ${INK}></path>
      <path d="M50 96 V30 M38 42 L50 28 L62 42" fill="none" stroke="var(--il-line)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"></path></svg>`,
    ask: `<svg viewBox="0 0 280 130" aria-hidden="true"><path d="M64 18 H196 a14 14 0 0 1 14 14 V82 a14 14 0 0 1 -14 14 H112 L86 116 V96 H64 a14 14 0 0 1 -14 -14 V32 a14 14 0 0 1 14 -14 Z" fill="var(--il-paper)" ${INK}></path>
      ${face(130, 50, 1)}<path d="M76 76 H184" ${INK} stroke-width="3" opacity=".35"></path>
      <circle cx="222" cy="86" r="21" fill="var(--il-mint)" ${INK}></circle><path d="M238 102 L252 116" fill="none" stroke="var(--il-line)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"></path><path d="M212 90 V82 M222 90 V76 M232 90 V84" fill="none" ${INK} stroke-width="3.5"></path></svg>`,
    prove: `<svg viewBox="0 0 280 130" aria-hidden="true"><rect x="84" y="10" width="102" height="110" rx="10" fill="var(--il-paper)" ${INK}></rect>${face(135, 42, .95)}
      <path d="M102 74 H168 M102 90 H150" ${INK} stroke-width="3.4" opacity=".4"></path>
      <circle cx="188" cy="92" r="25" fill="var(--il-mint)" ${INK}></circle><path d="M176 93 L185 102 L201 84" fill="none" ${INK} stroke-width="5.5"></path></svg>`,
  };
  const emptyArt = (titleText, body, cta = "") => `<div class="empty-art">${mascotMini}<b>${esc(titleText)}</b><p>${esc(body)}</p>${cta}</div>`;

  // ------------------------------------------------------------------ shared wording built from the live TAT rules
  const seconds = ms => `${fmt.n(Math.round(Number(ms) / 100) / 10)} s`;
  const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };
  // "P2M by T+5, P2P by T+1" and "₹100"; each rate is shown separately if the rules ever differ
  function ruleParts(rules) {
    const rates = [...new Set(rules.map(r => String(r.RS_PER_DAY)))];
    return { deadlines: rules.map(r => `${esc(r.TXN_TYPE)} by T+${fmt.n(r.TAT_DAYS)}${rates.length > 1 ? ` (${fmt.rs(r.RS_PER_DAY)}/day)` : ""}`).join(", "),
      rate: rates.length === 1 ? `${fmt.rs(rates[0])} a day` : "a daily amount" };
  }

  // ------------------------------------------------------------------ page: home
  PAGES.home = async (app) => {
    const o = await call("/api/overview").catch(() => null);   // the intro still renders with the database down
    if (o) setContext(o);
    const k = o ? o.kpi : {}, v = o ? o.volume : {};
    const r = o ? ruleParts(o.rules) : null, name = who.get().split(/[\s,]+/)[0];
    const how = [
      { icon: "git-compare-arrows", t: "Match", d: "Lines up the UPI switch, NPCI settlement and core-banking ledger for every payment.",
        proof: o ? `${fmt.n(v.TXNS)} transactions${isNum(o.recon_ms) ? ` in ${seconds(o.recon_ms)}` : ""}` : "" },
      { icon: "timer", t: "Start the clock", d: "Finds the customers who were debited and not refunded, then applies the deadline.",
        proof: o ? `${plural(k.OPEN_CASES, "open case")}` : "" },
      { icon: "list-ordered", t: "Rank the work", d: "Puts what adds cost tomorrow first, so the team knows what to do next.",
        proof: o ? `${fmt.rs(k.NEW_ACCRUAL_RS)} avoidable tomorrow` : "" },
      { icon: "badge-check", t: "Approve and prove", d: "A named person approves each fix. Every step goes into the audit log.",
        proof: o ? `${plural(o.pending, "proposal")} waiting` : "" },
    ];
    const starts = [
      { href: "#/dashboard", tint: "t-gold", art: ART.today, t: "See today's priorities", d: "What costs money tomorrow, and the three things to do about it" },
      { href: "#/queue?focus=accruing", tint: "t-rose", art: ART.queue, t: "Work the queue", d: "Every case in order, with the fix one click away" },
      { href: "#/assistant", tint: "t-blue", art: ART.ask, t: "Ask the assistant", d: "Plain questions, answered from SQL you can open and check" },
      { href: "#/actions", tint: "t-mint", art: ART.prove, t: "Approve and prove", d: "Decide proposals, then show who did what and when" },
    ];
    app.innerHTML = `
      <section class="hero" id="home-hero">
        <div class="hero-copy">
          <p class="hero-eyebrow">${esc(greeting())}${name ? `, ${esc(name)}` : ""}</p>
          <h1>Every stuck rupee,<br>on a clock.</h1>
          <p class="hero-lead">A UPI payment fails, but the customer is still debited. The bank has a deadline to return the money, and after that it owes compensation every day. TAT Guard finds those cases, ranks them and proves what was done.</p>
          ${r ? `<p class="hero-rule"><b>Deadlines:</b> ${r.deadlines}, then ${r.rate}, without waiting for a complaint.</p>` : `<p class="hero-rule"><b>No data yet.</b> Connect to Exasol and import a dataset to begin.</p>`}
          <div class="hero-cta"><button class="btn gold" data-tour-start type="button"><i data-lucide="play"></i>Start guided demo</button>
            <a class="btn on-dark" href="#/connect">Connect and import</a>
            <a class="btn on-dark" href="#/dashboard">Open today's work<i data-lucide="arrow-right"></i></a></div>
        </div>
        <div class="hero-art">${MASCOT}</div>
        ${o ? `<dl class="hero-stats">
          <div><dt>Added tomorrow if nothing changes</dt><dd class="hot">${fmt.rs(k.NEW_ACCRUAL_RS)}</dd></div>
          <div><dt>Cases adding cost</dt><dd>${fmt.n(k.ACCRUING_N)}</dd></div>
          <div><dt>Customer money stuck</dt><dd>${fmt.rs(k.STUCK_RS)}</dd></div></dl>` : ""}
      </section>
      <section class="section" id="home-how">
        <div class="section-head"><h2>How it works</h2><p>Four steps, every one running on your own Exasol database.</p></div>
        <ol class="how">${how.map(h => `<li><span class="how-num"><i data-lucide="${h.icon}"></i></span><h3>${esc(h.t)}</h3><p>${esc(h.d)}</p>${h.proof ? `<span class="proof">${h.proof}</span>` : ""}</li>`).join("")}</ol>
      </section>
      <section class="section">
        <div class="section-head"><h2>Where do you want to start?</h2></div>
        <div class="starts">${starts.map(s => `<a class="start ${s.tint}" href="${s.href}"><span class="start-art">${s.art}</span><b>${esc(s.t)}</b><span class="d">${esc(s.d)}</span></a>`).join("")}</div>
      </section>
      <footer class="home-foot"><span>${o ? `Showing ${esc(o.dataset.name)}: ${fmt.n(v.TXNS)} transactions in Exasol, read by live queries.` : "Nothing loaded."} <a href="#/connect">Where this data comes from</a></span><span>File layouts are stand-ins, not real NPCI, switch or CBS formats.</span></footer>`;
  };

  // ------------------------------------------------------------------ page: today
  PAGES.dashboard = async (app) => {
    const [o, t, top] = await Promise.all([call("/api/overview"), call("/api/trend"), call("/api/queue?sort=rank&size=10")]);
    setContext(o);
    if (!Number(o.volume.TXNS)) {
      app.innerHTML = head("Today", "See what adds cost tomorrow, fix that first, and prove compensation was paid.") + `<section class="card">${emptyArt("No data loaded", "Connect to Exasol and import a dataset. Every number here comes from it.", `<a class="btn primary" href="#/connect"><i data-lucide="plug-zap"></i>Connect and import</a>`)}</section>`;
      return;
    }
    const k = o.kpi;
    // "What needs doing": built only from live counts, so a step disappears when its work is done
    const steps = [];
    if (Number(k.ACCRUING_N) > 0) steps.push({ tone: "danger", title: `Stop the clock on ${plural(k.ACCRUING_N, "case")}`,
      body: `They add ${fmt.rs(k.NEW_ACCRUAL_RS)} tomorrow. Start with the customers waiting longest.`, go: ["queue", { focus: "accruing" }] });
    if (Number(k.COMP_DUE_N) > 0) steps.push({ tone: "violet", title: `Pay ${fmt.rs(k.COMP_DUE_RS)} of compensation`,
      body: `${plural(k.COMP_DUE_N, "reversed case")} still owe the customer, due without a complaint.`, go: ["queue", { state: "COMPENSATION_DUE" }] });
    o.missing_files.forEach(f => steps.push({ tone: "warn", title: `Chase the ${fmt.day(f.SETTLEMENT_DT)} cycle ${fmt.n(f.CYCLE_NO)} settlement file`,
      body: `Expected ${fmt.dt(f.EXPECTED)}. ${plural(f.BREAKS, "break")} cannot be confirmed until it arrives.`, go: ["sources", {}] }));
    if (Number(o.pending) > 0) steps.push({ tone: "info", title: `Decide ${plural(o.pending, "proposal")}`,
      body: "Nothing changes until a named person approves.", go: ["actions", { status: "PROPOSED" }] });
    const stats = [
      { tone: "brand", icon: "wallet", label: "Customer money stuck", value: fmt.rs(k.STUCK_RS), sub: `${plural(k.OPEN_CASES, "debit-no-credit case")} open`, go: ["queue", { class: "DEBIT_NO_CREDIT" }] },
      { tone: "danger", icon: "clock-alert", label: "Overdue", value: fmt.n(k.OVERDUE_N), sub: `${fmt.rs(k.OVERDUE_RS)} accrued so far`, go: ["queue", { state: "OVERDUE" }] },
      { tone: "warn", icon: "triangle-alert", label: "Due today", value: fmt.n(k.AT_RISK_N), sub: "Reversed today, these never accrue", go: ["queue", { state: "AT_RISK" }] },
      { tone: "violet", icon: "hand-coins", label: "Compensation due", value: fmt.rs(k.COMP_DUE_RS), sub: `${plural(k.COMP_DUE_N, "reversed case")}`, go: ["queue", { state: "COMPENSATION_DUE" }] },
    ];
    app.innerHTML = head("Today", "See what adds cost tomorrow, fix that first, and prove compensation was paid.") + `
      <div class="today-top">
        <button class="cost-card" id="today-cost" type="button">
          <span><span class="cost-label">Added tomorrow if nothing changes</span><br><span class="cost-value">${fmt.rs(k.NEW_ACCRUAL_RS)}</span></span>
          <span class="cost-sub">${plural(k.ACCRUING_N, "case")} accruing · ${fmt.rs(k.OWED_TOMORROW_RS)} owed in total</span>
          <span class="cost-go">Open these cases<i data-lucide="arrow-right"></i></span>
          ${spark(t.points.map(p => p.OPEN_RS))}
        </button>
        <section class="card" id="today-steps" aria-label="What needs doing">
          <div class="card-head"><h3>What needs doing</h3></div>
          ${steps.length ? `<ol class="todo">${steps.map((c, i) => `<li class="tone-${c.tone}"><button data-step="${i}" type="button"><span class="todo-n">${i + 1}</span><span><b>${esc(c.title)}</b><small>${esc(c.body)}</small></span><i data-lucide="arrow-right"></i></button></li>`).join("")}</ol>`
            : emptyArt("All clear", "Nothing needs action right now.")}
        </section>
      </div>
      <div class="stats">${stats.map((c, i) => `<button class="stat tone-${c.tone}" data-stat="${i}" type="button">
          <span class="stat-label"><i data-lucide="${c.icon}"></i>${esc(c.label)}</span><span class="stat-value">${c.value}</span><span class="stat-sub">${c.sub}</span></button>`).join("")}</div>
      <section class="card">
        <div class="card-head"><h3>Do these first</h3><a class="btn sm" href="#/queue">Open work queue<i data-lucide="arrow-right"></i></a></div>
        <div class="table-wrap" style="margin-top:12px"><table class="data">${queueHeader(false)}<tbody>${top.rows.slice(0, 5).map(r => queueRow(r)).join("")}</tbody></table></div>
        <div class="card-foot"><span>Ranked by what a case adds tomorrow, then time waited · ${plural(top.total, "row")} in the queue</span><span class="timing">${top.ms} ms</span></div>
      </section>
      <a class="more-link" href="#/insights">See the charts behind these numbers<i data-lucide="arrow-right"></i></a>`;
    $("#today-cost").addEventListener("click", () => go("queue", { focus: "accruing" }));
    $$("[data-stat]", app).forEach(b => b.addEventListener("click", () => go(...stats[Number(b.dataset.stat)].go)));
    $$("[data-step]", app).forEach(b => b.addEventListener("click", () => go(...steps[Number(b.dataset.step)].go)));
    bindRowClicks(app);
  };

  // ------------------------------------------------------------------ page: insights (one topic at a time)
  const INSIGHT_TABS = [["cost", "Cost over time", "chart-line"], ["breaks", "Break types", "chart-bar"], ["age", "Age and banks", "hourglass"], ["comp", "Compensation", "badge-check"]];
  PAGES.insights = async (app, p) => {
    const tab = INSIGHT_TABS.some(x => x[0] === p.tab) ? p.tab : INSIGHT_TABS[0][0];
    const [o, t] = await Promise.all([call("/api/overview"), tab === "cost" ? call("/api/trend") : null]);
    setContext(o);
    const v = o.volume;
    let body = "";
    if (tab === "cost") {
      const tatBlock = o.tat.map(tt => {
        const tot = Math.max(Number(tt.TOTAL), 1);
        const seg = (n, cls) => Number(n) > 0 ? `<span class="${cls}" style="width:${100 * Number(n) / tot}%"></span>` : "";
        return `<div class="tat-type"><h4><span>${esc(tt.TXN_TYPE)} <span class="muted" style="font-weight:500">(T+${fmt.n(tt.TAT_DAYS)} days)</span></span><span>${fmt.n(tt.TOTAL)}</span></h4>
          <div class="stack">${seg(tt.OVERDUE, "bg-danger")}${seg(tt.AT_RISK, "bg-warn")}${seg(tt.WITHIN_TAT, "bg-info")}${seg(tt.REVERSED, "bg-neutral")}</div>
          <div class="tat-nums">
            <button data-go-state="OVERDUE"><b class="c-danger">${fmt.n(tt.OVERDUE)}</b><small>Overdue</small></button>
            <button data-go-state="AT_RISK"><b class="c-warn">${fmt.n(tt.AT_RISK)}</b><small>Due today</small></button>
            <button data-go-state="WITHIN_TAT"><b class="c-info">${fmt.n(tt.WITHIN_TAT)}</b><small>Within TAT</small></button>
            <button data-go-state="COMPENSATION_DUE" title="Opens the ${fmt.n(tt.COMP_DUE)} reversed cases whose compensation is missing or short"><b>${fmt.n(tt.REVERSED)}</b><small>Reversed · ${fmt.n(tt.COMP_DUE)} comp. due</small></button>
          </div></div>`;
      }).join("");
      const r = ruleParts(o.rules);
      body = `<div class="grid"><div class="span-8">${card("Compensation liability by day", "chart-line", trendChart(t.points) + `<div class="legend" style="margin-top:8px">
          <span><i class="sw" style="background:var(--brand)"></i>Owed on cases still open</span><span><i class="sw" style="background:var(--series-2)"></i>Accrued on all cases</span>
          <span><i class="sw dash"></i>* tomorrow, projected</span></div>`, "", `<span>Penalty days = calendar days beyond T+TAT, per case, up to its reversal</span><span class="timing">${t.ms} ms</span>`)}</div>
        <div class="span-4">${card("TAT status by type", "timer", tatBlock || `<div class="empty">No debit-no-credit cases.</div>`, "", `<span>${r.deadlines}, then ${r.rate} (${esc(o.rules.map(x => x.FACT_ID).join(", "))})</span>`)}</div></div>`;
    } else if (tab === "breaks") {
      const sorted = [...o.classes].sort((a, b) => Number(b.N) - Number(a.N)), maxN = Math.max(...sorted.map(c => Number(c.N)), 1), topC = sorted[0];
      body = card("Exceptions by break type", "chart-bar", `${topC ? `<p class="lede">${esc(classMeta(topC.CLASS).label)} is ${fmt.pct(topC.PCT)} of all exceptions.</p>` : ""}
        ${sorted.map(c => `<button class="break-row" type="button" data-class="${esc(c.CLASS)}" title="Open in work queue">${classTag(c.CLASS)}<span class="bar"><i style="width:${100 * Number(c.N) / maxN}%"></i></span><b>${fmt.n(c.N)}</b><em>${fmt.pct(c.PCT)}</em></button>`).join("") || `<div class="empty">No exceptions.</div>`}`, "",
        `<span>${fmt.pct(v.EXCEPTION_PCT)} of ${fmt.n(v.TXNS)} transactions · select a type to open it</span><span class="timing">${o.ms.classes} ms</span>`);
    } else if (tab === "age") {
      const ageMax = Math.max(...o.ageing.map(a => Number(a.N)), 1);
      const ageing = o.ageing.map(a => `<div class="bar-row"><span>${Number(a.DAYS) ? `${plural(a.DAYS, "day")} past TAT` : "Not past TAT"}</span>
          <span class="bar"><i class="${Number(a.DAYS) ? "bg-danger" : "bg-info"}" style="width:${100 * Number(a.N) / ageMax}%"></i></span><b>${fmt.n(a.N)}</b><em>${fmt.rs(a.STUCK_RS)}</em></div>`).join("");
      const banks = o.banks.map(b => `<tr class="clickable" data-bank="${esc(b.BANK)}" tabindex="0" aria-label="Open ${esc(b.BANK)} cases"><td>${esc(b.BANK)}</td><td class="n">${fmt.n(b.N)}</td><td class="n">${fmt.n(b.OVERDUE_N)}</td><td class="n">${fmt.rs(b.STUCK_RS)}</td><td class="n">${Number(b.NEW_ACCRUAL_RS) > 0 ? `<b class="c-danger">+${fmt.rs(b.NEW_ACCRUAL_RS)}</b>` : "–"}</td></tr>`).join("");
      const p2p = o.rules.find(r => r.TXN_TYPE === "P2P");
      body = `<div class="grid"><div class="span-6">${card("Open cases by age", "hourglass", ageing || `<div class="empty">No open debit-no-credit cases.</div>`, "", `<span>Calendar days past TAT, with customer money stuck</span><span class="timing">${o.ms.ageing} ms</span>`)}</div>
        <div class="span-6">${card("Chase list by payee bank", "landmark", banks ? `<div class="table-wrap"><table class="data"><thead><tr><th>Payee bank</th><th class="n">Open</th><th class="n">Overdue</th><th class="n">Stuck</th><th class="n">Adds</th></tr></thead><tbody>${banks}</tbody></table></div>` : `<div class="empty">No open debit-no-credit cases.</div>`, "",
          `<span>The beneficiary bank owns the P2P auto-reversal${p2p ? ` (${esc(p2p.FACT_ID)})` : ""}</span><span class="timing">${o.ms.banks} ms</span>`)}</div></div>`;
    } else {
      const comp = o.compensation.map(c => { const m = COMP_META[c.COMP_STATUS] || { label: title(c.COMP_STATUS), tone: "neutral" };
        return `<div class="row between comp-row"><span>${pill(m.label, m.tone)}</span><span><b>${fmt.n(c.N)}</b>${Number(c.GAP_RS) > 0 ? ` <span class="muted">· ${fmt.rs(c.GAP_RS)} short</span>` : Number(c.PAID_RS) > 0 ? ` <span class="muted">· ${fmt.rs(c.PAID_RS)} paid</span>` : ""}</span></div>`; }).join("");
      body = `<div style="max-width:720px">${card("Compensation register", "badge-check", comp || `<div class="empty">No debit-no-credit cases.</div>`, `<a class="btn sm" href="/api/compensation.csv" download><i data-lucide="download"></i>Export</a>`, `<span>Every case past TAT, whether or not the customer complained</span><span class="timing">${o.ms.compensation} ms</span>`)}</div>`;
    }
    app.innerHTML = head("Insights", "The picture behind the numbers, one topic at a time.") +
      `<div class="seg" role="tablist" aria-label="Insight topics">${INSIGHT_TABS.map(([id, label, icon]) => `<button role="tab" aria-selected="${id === tab}" class="${id === tab ? "active" : ""}" data-itab="${id}" type="button"><i data-lucide="${icon}"></i>${esc(label)}</button>`).join("")}</div>${body}`;
    $$("[data-itab]", app).forEach(b => b.addEventListener("click", () => go("insights", { tab: b.dataset.itab })));
    $$("[data-class]", app).forEach(b => b.addEventListener("click", () => go("queue", { class: b.dataset.class })));
    $$("[data-bank]", app).forEach(b => {
      const open = () => go("queue", { class: "DEBIT_NO_CREDIT", bank: b.dataset.bank });
      b.addEventListener("click", open);
      b.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
    });
    $$("[data-go-state]", app).forEach(b => b.addEventListener("click", () => go("queue", { state: b.dataset.goState, class: "DEBIT_NO_CREDIT" })));
    if (t) bindTrend(t.points);
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
      `<a class="btn" href="/api/queue.csv${csvQs ? "?" + csvQs : ""}" download><i data-lucide="download"></i>Export this view</a>`) + `
      <section class="card">
        <div class="tabs">${tabs.map((t, i) => `<button class="tab ${t.on ? "active" : ""}" ${t.on ? 'aria-pressed="true"' : 'aria-pressed="false"'} data-tab="${i}" type="button">${esc(t.label)} <em>${fmt.n(t.n)}</em></button>`).join("")}</div>
        <form class="toolbar" id="qf">
          <label class="search"><i data-lucide="search"></i><input name="q" value="${esc(params.q)}" placeholder="Search by UPI id, RRN or exception id" maxlength="40"></label>
          <select name="class" aria-label="Break type"><option value="">All break types</option>${r.classes.map(c => `<option value="${esc(c)}" ${c === params.class ? "selected" : ""}>${esc(classMeta(c).label)}</option>`).join("")}</select>
          <select name="sort" aria-label="Sort">${state.meta.queue_sorts.map(v => `<option value="${esc(v)}" ${v === params.sort ? "selected" : ""}>Sort: ${esc(SORT_LABEL[v] || title(v).toLowerCase())}</option>`).join("")}</select>
          ${params.bank ? `<span class="pill neutral">Payee bank: ${esc(params.bank)}</span>` : ""}
          ${params.q || params.class || params.bank ? `<button class="btn ghost" type="button" id="qclear">Clear</button>` : ""}
        </form>
        <details class="note"><summary><i data-lucide="info"></i>How is this ranked?</summary><p>Compensation is a flat amount per day, so every accruing case costs the same to leave open. Those come first, longest wait first. Compensation already owed comes next, then cases still inside TAT, then breaks with no TAT clock.</p></details>
        <div class="bulkbar" id="bulk" hidden></div>
        <div class="table-wrap" id="queue-table"><table class="data">${queueHeader(true)}<tbody>${r.rows.map(x => queueRow(x, { select: true })).join("") || `<tr><td colspan="8"><div class="empty">Nothing matches these filters.</div></td></tr>`}</tbody></table></div>
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

  // ------------------------------------------------------------------ page: connect and import
  // Every figure in the app is read from RAW and RECON in Exasol; this page is how data gets there (ui/importer.py).
  const FILE_LABEL = { "switch_log.csv": "UPI switch log", "npci_settlement.csv": "NPCI settlement file", "cbs_ledger.csv": "Core-banking ledger", "settlement_file_log.csv": "Settlement file arrivals" };
  const TABLE_LABEL = { "RAW.SWITCH_LOG": "UPI switch log", "RAW.NPCI_SETTLEMENT": "NPCI settlement file", "RAW.CBS_LEDGER": "Core-banking ledger", "RAW.SETTLEMENT_FILE_LOG": "Settlement file arrivals" };
  const STEP_LABEL = { "check data": "Check the new data", schemas: "Create the tables", settings: "Load settings and TAT rules", "read-only user": "Create the read-only user",
    "recon 20_udfs.sql": "Install the narration parser", "recon 10_match_pass1.sql": "Match pass 1: exact id", "recon 10_match_pass2.sql": "Match pass 2: RRN and time window",
    "recon 10_match_pass3.sql": "Match pass 3: ledger narrations", "recon 10_match_pass4.sql": "Match pass 4: fuzzy", "recon 15_classify.sql": "Classify every break", "recon 30_penalty_view.sql": "Start the TAT clocks" };
  const stepLabel = n => n.startsWith("load ") ? `Load ${TABLE_LABEL[n.slice(5)] || n.slice(5)}` : (STEP_LABEL[n] || n);
  const SOURCE_TEXT = { sample: "Written by generator/generate.py. Not real payments", upload: "CSV files you uploaded", schema: "Copied from another Exasol schema" };
  const mb = n => Number(n) >= 1e9 ? `${(Number(n) / 1e9).toFixed(1)} GB` : `${fmt.n(Math.round(Number(n) / 1e6))} MB`;
  const inputRow = (id, label, value, type = "text", hint = "") => `<label class="fld"><span>${esc(label)}</span><input class="field" id="${id}" type="${type}" value="${esc(value)}" autocomplete="off"${hint ? ` placeholder="${esc(hint)}"` : ""}></label>`;
  function sendFile(name, file, onPct) {
    return new Promise((ok, no) => {
      const id = state.imp.uploadId, x = new XMLHttpRequest();
      x.open("POST", `/api/upload?file=${encodeURIComponent(name)}${id ? "&id=" + id : ""}`);
      x.setRequestHeader("Content-Type", "application/octet-stream");
      x.upload.onprogress = e => { if (e.lengthComputable) onPct(Math.round(100 * e.loaded / e.total)); };
      x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch (e) { /* non-JSON error */ } if (x.status < 300) ok(d); else no(new Error(d.error || x.statusText)); };
      x.onerror = () => no(new Error("The upload failed. Is the server running?"));
      x.send(file);
    });
  }
  function jobHtml(j) {
    const row = s => `<li class="job-${s.state}"><i data-lucide="${{ done: "circle-check", running: "loader-circle", failed: "circle-x" }[s.state] || "circle"}"></i><span>${esc(stepLabel(s.name))}</span>
      <em>${isNum(s.rows) ? `${fmt.n(s.rows)} rows · ` : ""}${isNum(s.ms) ? seconds(s.ms) : ""}</em></li>`;
    const half = j.steps.findIndex(s => s.name.startsWith("recon "));
    const total = j.steps.reduce((a, s) => a + (Number(s.ms) || 0), 0);
    const head = j.status === "running" ? `Importing ${esc(j.name)}` : j.status === "done" ? "Import finished" : "The import stopped";
    return `<section class="card" id="job"><div class="card-head"><h3>${head}</h3><span class="timing">${total ? `${seconds(total)} in Exasol` : ""}</span></div>
      <div class="card-body"><div class="job-cols"><div><p class="section-title">Load</p><ul class="job">${j.steps.slice(0, half).map(row).join("")}</ul></div>
        <div><p class="section-title">Reconcile</p><ul class="job">${j.steps.slice(half).map(row).join("")}</ul></div></div>
      ${j.status === "done" ? `<div class="job-end"><span><b>${fmt.n(j.summary.transactions)}</b> transactions · <b>${fmt.n(j.summary.exceptions)}</b> exceptions · <b>${fmt.n(j.summary.queue)}</b> in the queue</span><a class="btn primary" href="#/dashboard">See today's priorities<i data-lucide="arrow-right"></i></a></div>` : ""}
      ${j.status === "failed" ? `<div class="error-box" style="margin-top:14px"><div>${esc(j.error)}</div></div><p class="muted small" style="margin:8px 0 0">${j.steps[0].name === "check data" && j.steps[0].state === "failed" ? "The new data failed its check, so your current data was not touched." : "The tables may now be empty or part-filled. Fix the data and import again, or reload the sample dataset below."}</p>` : ""}
      </div></section>`;
  }
  PAGES.connect = async (app) => {
    clearInterval(state.impTimer);
    const c = await call("/api/connection"), first = c.samples[0];
    const f = state.imp = { source: first ? "sample" : "upload", dataset: first ? first.id : "", schema: c.schemas[0] || "", uploadId: "", files: {}, name: "", asOf: "", reset: true, ok: false, ...state.imp };
    if (!c.samples.some(s => s.id === f.dataset)) f.dataset = first ? first.id : "";
    if (!c.schemas.includes(f.schema)) f.schema = c.schemas[0] || "";
    const d = c.dataset, job = c.job, busy = job.status === "running", host = c.dsn.split(/[/:]/)[0];
    const lineage = `<section class="lineage" id="lineage" aria-label="Where the data on these screens comes from">
      <div><small>1. Source</small><b>${d ? esc(d.name) : "Nothing loaded yet"}</b><span>${d ? esc(SOURCE_TEXT[d.source] || "") : "Choose a dataset below"}</span></div><i data-lucide="arrow-right"></i>
      <div><small>2. Stored in</small><b>${c.connected ? `Exasol ${esc(String(c.version).split("-")[0])}` : "Not connected"}</b><span>${d ? `${fmt.n(d.rows)} transactions on ${esc(host)}` : esc(host)}</span></div><i data-lucide="arrow-right"></i>
      <div><small>3. Reconciled by</small><b>SQL inside Exasol</b><span>Schemas RAW, then RECON</span></div><i data-lucide="arrow-right"></i>
      <div><small>4. Shown here</small><b>Every screen</b><span>Live queries. No figure is stored in the page</span></div></section>`;
    app.innerHTML = head("Connect and import", "Connect to Exasol, choose your data, and run the reconciliation. Every number in this app comes from here.") + lineage +
      `<div id="job-slot"></div><div id="import-form"${busy ? " hidden" : ""}>
      <section class="card step-card"><div class="card-head"><h3><span class="todo-n">1</span>Connect to Exasol</h3>${c.connected ? `<span class="pill brand">Connected</span>` : `<span class="pill danger">Not connected</span>`}</div>
        <div class="card-body">${c.connected ? `<p class="flat">Exasol ${esc(c.version)} at <span class="mono">${esc(c.dsn)}</span>, as ${esc(c.user)}.</p>` : `<div class="error-box">${esc(c.error || "No connection set.")}</div><p class="muted small" style="margin:8px 0 0">Local database stopped? Run <span class="mono">podman machine start</span>, then <span class="mono">exasol start</span>, and reload this page.</p>`}
          <details class="plain"${c.connected ? "" : " open"}><summary>${c.connected ? "Use a different Exasol database" : "Enter a connection"}</summary><div class="flds">
            ${inputRow("c-dsn", "DSN (host/fingerprint:port)", c.dsn, "text", "127.0.0.1/nocertcheck:8563")}${inputRow("c-user", "User", c.user)}${inputRow("c-pwd", "Password", "", "password", "Blank keeps the saved password")}</div>
            <div class="row wrapped"><button class="btn" id="c-test" type="button"><i data-lucide="plug-zap"></i>Test</button><button class="btn primary" id="c-use" type="button">Use this database</button><span class="muted small" id="c-result">Kept in memory until the server stops. Never written to disk.</span></div></details></div></section>
      <section class="card step-card"><div class="card-head"><h3><span class="todo-n">2</span>Choose your data</h3></div><div class="card-body">
        <div class="choices" role="radiogroup" aria-label="Data source">${[["sample", "database", "Sample dataset", "Synthetic payments with known breaks. Best for a demo"], ["upload", "upload", "Upload CSV files", "Your four files, in the layouts shown here"], ["schema", "table-2", "Tables in Exasol", "Copy four tables you already have in a schema"]].map(([k, ic, t, s]) =>
          `<button class="choice ${f.source === k ? "active" : ""}" role="radio" aria-checked="${f.source === k}" data-source="${k}" type="button"><i data-lucide="${ic}"></i><b>${t}</b><span>${s}</span></button>`).join("")}</div>
        <div id="choice-body"></div></div></section>
      <section class="card step-card"><div class="card-head"><h3><span class="todo-n">3</span>Import and reconcile</h3></div><div class="card-body" id="go-body"></div></section></div>`;
    const drawChoice = () => {
      $$("[data-source]", app).forEach(b => { const on = b.dataset.source === f.source; b.classList.toggle("active", on); b.setAttribute("aria-checked", on); });
      const body = $("#choice-body");
      if (f.source === "sample") {
        body.innerHTML = c.samples.length ? `<div class="pick">${c.samples.map(s => `<label><input type="radio" name="ds" value="${esc(s.id)}" ${s.id === f.dataset ? "checked" : ""}><span><b>${fmt.n(s.rows)} transactions</b> <span class="muted">${esc(s.folder)} · ${mb(s.bytes)}${s.id === first.id ? "" : " · much slower"}</span></span></label>`).join("")}</div>`
          : `<p class="flat muted">No sample dataset yet. Create one with <span class="mono">python generator/generate.py</span>.</p>`;
      } else if (f.source === "upload") {
        body.innerHTML = `<p class="flat muted small">Each file needs this exact header, in this order. These are TAT Guard's stand-in layouts, not real NPCI, switch or CBS formats.${first ? ` To try it, use the files in <span class="mono">${esc(first.folder)}</span>.` : ""}</p>
          <div class="slots">${Object.entries(c.files).map(([n, cols]) => { const s = f.files[n] || {}; return `<div class="slot ${s.done ? "ok" : s.error ? "bad" : ""}"><div><b>${esc(FILE_LABEL[n] || n)}</b><span class="mono wrap">${esc(cols.join(", "))}</span>${s.error ? `<span class="c-danger">${esc(s.error)}</span>` : ""}</div>
            <label class="btn sm">${s.done ? `<i data-lucide="circle-check"></i>${mb(s.done)}` : isNum(s.pct) ? `Uploading ${s.pct}%` : `<i data-lucide="upload"></i>Choose file`}<input type="file" accept=".csv,text/csv" data-slot="${esc(n)}" hidden></label></div>`; }).join("")}</div>`;
      } else {
        body.innerHTML = c.schemas.length ? `<label class="fld"><span>Schema</span><select id="i-schema">${c.schemas.map(s => `<option ${s === f.schema ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>`
          : `<p class="flat muted">No schema here holds all four tables yet: ${Object.keys(c.files).map(n => n.replace(".csv", "").toUpperCase()).join(", ")}. Create them with the columns listed under Upload CSV files, then reload this page.</p>`;
      }
      icons(body);
      $$("input[name=ds]", body).forEach(r => r.addEventListener("change", () => { f.dataset = r.value; }));
      if ($("#i-schema")) $("#i-schema").addEventListener("change", e => { f.schema = e.target.value; });
      $$("[data-slot]", body).forEach(inp => inp.addEventListener("change", async () => {
        const n = inp.dataset.slot, file = inp.files[0];
        if (!file) return;
        f.files[n] = { pct: 0 }; drawChoice(); drawGo();
        try {
          const r = await sendFile(n, file, p => { f.files[n] = { pct: p }; const lab = $(`[data-slot="${n}"]`); if (lab) lab.parentElement.firstChild.textContent = `Uploading ${p}%`; });
          f.uploadId = r.upload_id; f.files[n] = { done: r.bytes };
        } catch (e) { f.files[n] = { error: e.message }; }
        drawChoice(); drawGo();
      }));
    };
    const drawGo = () => {
      const own = f.source !== "sample", g = $("#go-body");
      g.innerHTML = `${own ? `<div class="flds">${inputRow("i-name", "Name for this data", f.name, "text", f.source === "upload" ? "Uploaded files" : "Exasol schema")}${inputRow("i-asof", "Cut-off (optional)", f.asOf, "text", "Newest transaction, if blank")}</div>
        <label class="tick"><input type="checkbox" id="i-ok" ${f.ok ? "checked" : ""}><span>This is public or synthetic data, with no real customer or employer data. TAT Guard has no login and is a demo.</span></label>` : ""}
        <label class="tick"><input type="checkbox" id="i-reset" ${f.reset ? "checked" : ""}><span>Clear proposals and the audit log. They refer to the data being replaced.</span></label>
        <div class="row wrapped" style="margin-top:12px"><button class="btn primary" id="i-go" type="button" ${c.connected ? "" : "disabled"}><i data-lucide="play"></i>Import and reconcile</button><span class="muted small">This replaces all the data now in RAW and RECON${d ? `, currently ${esc(d.name)}` : ""}.</span></div>`;
      icons(g);
      if ($("#i-name")) $("#i-name").addEventListener("input", e => { f.name = e.target.value; });
      if ($("#i-asof")) $("#i-asof").addEventListener("input", e => { f.asOf = e.target.value; });
      if ($("#i-ok")) $("#i-ok").addEventListener("change", e => { f.ok = e.target.checked; });
      $("#i-reset").addEventListener("change", e => { f.reset = e.target.checked; });
      $("#i-go").addEventListener("click", async e => {
        const b = e.currentTarget;
        if (!b.dataset.armed) {   // two-step confirmation, as for approvals
          b.dataset.armed = "1"; b.textContent = "Confirm: replace all current data"; b.classList.add("danger-fill");
          setTimeout(() => { if (b.isConnected && b.dataset.armed) drawGo(); }, 6000);
          return;
        }
        b.disabled = true;
        try {
          const j = await call("/api/import", { source: f.source, dataset: f.dataset, upload_id: f.uploadId, schema: f.schema, name: f.name, as_of: f.asOf, reset_audit: f.reset, confirm_public: f.ok });
          Object.assign(f, { uploadId: "", files: {}, name: "", asOf: "", ok: false });   // the confirmation covers one import
          watch(j);
        } catch (err) { toast(esc(err.message), true); drawGo(); }
      });
    };
    const drawJob = j => { const slot = $("#job-slot"); if (!slot) return; slot.innerHTML = j.steps ? jobHtml(j) : ""; icons(slot); };
    function watch(j) {
      $("#import-form").hidden = true;
      drawJob(j);
      clearInterval(state.impTimer);
      state.impTimer = setInterval(async () => {
        if (parseHash().page !== "connect") return clearInterval(state.impTimer);
        try {
          const now = await call("/api/imports");
          drawJob(now);
          if (now.status !== "running") { clearInterval(state.impTimer); loadShell(); call("/api/overview").then(setContext).catch(() => { /* shown per page */ }); route(); }
        } catch (e) { /* keep polling: the server is busy loading */ }
      }, 1000);
    }
    drawJob(job);
    drawChoice();
    drawGo();
    $$("[data-source]", app).forEach(b => b.addEventListener("click", () => { f.source = b.dataset.source; drawChoice(); drawGo(); }));
    const conn = async use => {
      const out = $("#c-result");
      out.textContent = "Connecting…";
      try {
        const r = await call("/api/connect", { dsn: $("#c-dsn").value, user: $("#c-user").value, password: $("#c-pwd").value, use });
        if (use) { toast("Now using this database."); loadShell(); route(); } else out.textContent = `Connected: Exasol ${r.version}`;
      } catch (e) { out.textContent = e.message; }
    };
    $("#c-test").addEventListener("click", () => conn(false));
    $("#c-use").addEventListener("click", () => conn(true));
    if (busy) watch(job);
  };

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
        <div class="table-wrap"><table class="data"><thead><tr><th>Transaction</th><th>Type</th><th>Payee bank</th><th class="n">Amount</th><th>Switch</th><th>NPCI</th><th class="n">CBS debits</th><th>Result</th></tr></thead>
          <tbody>${r.rows.map(t => `<tr class="clickable" data-open="${esc(t.UPI_TXN_ID || t.RRN)}">
            <td><div class="mono">${esc(t.UPI_TXN_ID || "–")}</div><div class="cell-sub">${fmt.dt(t.TXN_TIME)} · RRN ${esc(t.RRN)}</div></td><td>${esc(t.TXN_TYPE || "–")}</td><td>${esc(t.PAYEE_BANK || "–")}</td>
            <td class="n">${fmt.rs(t.AMOUNT_RS)}</td><td>${esc(title(t.SW_STATUS) || "–")}</td><td>${t.NPCI_STATUS ? esc(title(t.NPCI_STATUS)) : `<span class="subtle">no record</span>`}</td>
            <td class="n">${fmt.n(t.DR_CNT)}</td><td>${t.CLASS ? classTag(t.CLASS) : pill("Reconciled", "brand")}</td></tr>`).join("") || `<tr><td colspan="8"><div class="empty">No transaction matches.</div></td></tr>`}</tbody></table></div>
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
    app.innerHTML = `<div class="chat">` + head("Assistant", "Ask about the reconciliation. Answers come only from SQL run on Exasol, and every query is shown.") + `
      <ul class="promise"><li><i data-lucide="database"></i>Read-only SQL</li><li><i data-lucide="check"></i>Every number checked against the results</li><li><i data-lucide="users"></i>Proposes, a person approves</li></ul>
      <section class="card"><div class="card-body">
        <div class="thread" id="thread"></div>
        <div id="starter"><div class="suggest" id="suggest">${state.meta.suggestions.map(s => `<button type="button" data-ask="${esc(s)}"><span>${esc(s)}</span><i data-lucide="arrow-right"></i></button>`).join("")}</div></div>
        <form class="askbox" id="ask-form"><input name="q" placeholder="e.g. Why did breaks spike?" maxlength="500" aria-label="Question" autocomplete="off"><button class="btn primary" type="submit"><i data-lucide="send"></i>Ask</button></form>
      </div>
      <details class="note" style="border-top:1px solid var(--line-2);border-bottom:0"><summary><i data-lucide="shield-check"></i>How it answers</summary><div class="kv" style="grid-template-columns:1fr;padding-bottom:12px">
        <div><dt>Mode</dt><dd>${h.agent_ready ? (h.agent_mode === "gemini" ? "Google Gemini, with read-only tools" : "Deterministic playbooks (no language model configured)") : esc(h.agent_error || "Starting…")}</dd></div>
        <div><dt>Reads</dt><dd>Through the official Exasol MCP server, as a database user that can only SELECT</dd></div>
        <div><dt>Numbers</dt><dd>Each number must appear in that turn's query results before it is shown. Open the queries to confirm what it means</dd></div>
        <div><dt>Changes</dt><dd>The assistant can only propose. A named person approves on the Approvals page</dd></div></div></details></section></div>`;
    const render = () => {
      $("#thread").innerHTML = state.thread.map(m => m.q ? `<div class="msg-q">${esc(m.q)}</div>` : answerHtml(m)).join("");
      $("#starter").style.marginTop = state.thread.length ? "14px" : "0";
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
    const q = (a.queries || []).map((r, i) => `<details class="sql"><summary><span>Query ${i + 1} · ${plural(r.row_count, "row")}</span><span class="timing">${fmt.n(r.ms)} ms</span></summary><pre>${esc(r.sql)}</pre>
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
    const [r, act] = await Promise.all([call("/api/actions" + (status ? "?status=" + encodeURIComponent(status) : "")), call("/api/activity?n=6")]);
    const all = Object.values(r.counts).reduce((a, b) => a + Number(b), 0);
    setPending(r.counts.PROPOSED || 0);
    // APPROVED is transient (decide() moves it on to EXECUTED/LOGGED/FAILED), so its tab shows only when rows sit there
    const tabs = [["", "All", all], ...state.meta.action_statuses.filter(s => s !== "APPROVED" || r.counts[s])
      .map(s => [s, STATUS_TAB[s] || title(s), r.counts[s] || 0])];
    app.innerHTML = head("Approvals", "Nothing changes until a named person approves. Approving runs a fixed SQL template, re-runs the reconciliation and writes the audit log.") + `
      <div class="grid"><div class="span-8"><section class="card" id="actions-list"><div class="tabs">${tabs.map(([s, l, n]) => `<button class="tab ${status === s ? "active" : ""}" data-st="${esc(s)}" type="button">${esc(l)} <em>${fmt.n(n)}</em></button>`).join("")}</div>
        <div>${r.rows.map(actionCard).join("") || emptyArt("Nothing here yet", "Propose a fix from the Work Queue or the Assistant, and it waits here for a decision.", `<a class="btn" href="#/queue?focus=accruing">Open the work queue<i data-lucide="arrow-right"></i></a>`)}</div>
        <div class="card-foot"><span>The only action types: ${Object.entries(state.meta.action_types).map(([k, d]) => `<span title="${esc(d)}">${esc(actionMeta(k).label)}</span>`).join(", ")}</span><span class="timing">${r.ms} ms</span></div></section></div>
        <div class="span-4">${card("Recent activity", "activity", `<div class="activity">${act.items.length ? act.items.map(activityItem).join("") : `<div class="empty">No proposals or approvals yet.</div>`}</div>`, `<a class="btn ghost sm" href="#/audit">Audit log<i data-lucide="arrow-right"></i></a>`)}</div></div>`;
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
      <div class="side-acts">${a.STATUS === "PROPOSED" ? `<button class="btn" data-decide="reject" data-id="${esc(a.ACTION_ID)}" type="button"><i data-lucide="x"></i>Reject</button>
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
    const side = btn.closest(".side-acts");
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
      <section class="card" id="audit-table"><div class="table-wrap"><table class="data"><thead><tr><th>Executed</th><th>Action</th><th>Target</th><th>Proposed by</th><th>Approved by</th><th>Outcome</th><th>Effect</th></tr></thead>
        <tbody>${r.rows.map(x => `<tr><td>${fmt.dt(x.EXECUTED)}</td>
          <td><b>${esc(actionMeta(x.ACTION_TYPE).label)}</b><div class="mono subtle">${esc(x.ACTION_ID)}</div></td>
          <td class="mono wrap">${esc(x.TARGET_REF)}</td><td>${esc(x.CREATED_BY || "–")}</td><td>${esc(x.EXECUTED_BY)}</td>
          <td>${pill(title(x.OUTCOME), STATUS_TONE[x.OUTCOME] || "neutral")}</td>
          <td>${eff(x)}<details class="sql"><summary><span>Executed SQL</span><i data-lucide="chevrons-up-down"></i></summary><pre>${esc(x.EXECUTED_SQL)}</pre></details></td></tr>`).join("")
          || `<tr><td colspan="7">${emptyArt("Nothing has been executed yet", "Approve a proposal and it appears here, with the exact SQL and the numbers before and after.")}</td></tr>`}</tbody></table></div>
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
    app.innerHTML = head("Data Sources", "The three sources the reconciliation reads, as loaded into Exasol, and the settlement files' arrival record.", `<a class="btn" href="#/connect"><i data-lucide="plug-zap"></i>Connect and import</a>`) + `
      <div class="grid"><div class="span-12 grid" id="source-cards">${s.tables.map(t => { const m = META[t.TABLE] || [t.TABLE, "table-2", "var(--neutral-soft);color:var(--text)"]; return `<div class="span-3"><section class="card source-card">
          <div class="top"><span class="ic" style="background:${m[2]}"><i data-lucide="${m[1]}"></i></span><div><h4>${esc(m[0])}</h4><div class="mono subtle">RAW.${esc(t.TABLE)}</div></div></div>
          <dl><div><dt>Rows</dt><dd>${fmt.n(t.ROWS)}</dd></div><div><dt>Columns</dt><dd>${fmt.n(t.COLS)}</dd></div><div><dt>Load time</dt><dd>${t.LOAD_MS !== null && t.LOAD_MS !== undefined ? fmt.n(Math.round(Number(t.LOAD_MS) / 100) / 10) + " s" : "–"}</dd></div></dl>
          <div class="muted" style="font-size:12.5px">Last loaded ${t.LOADED ? fmt.dt(t.LOADED) : "– (no load logged)"}</div></section></div>`; }).join("")}</div>
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
    d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false; document.body.classList.add("drawer-open");
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
        ${act ? `<div class="row wrapped"><button class="btn primary" id="drawer-propose" type="button"><i data-lucide="${actionMeta(act).icon}"></i>${esc(actionMeta(act).cta)}</button><span class="muted small">A named person approves it in Approvals.</span></div>` : ""}
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
        ${t.actions.length ? `<div><p class="section-title">Actions</p>${t.actions.map(a => `<div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line-2)"><span>${esc(actionMeta(a.ACTION_TYPE).label)} · ${esc(a.CREATED_BY)}</span>${pill(title(a.STATUS), STATUS_TONE[a.STATUS] || "neutral")}</div>`).join("")}</div>` : ""}`;
      icons(body);
      $$("[data-copy]", body).forEach(b => b.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(b.dataset.copy); toast("Copied."); } catch (err) { toast("Copy is not available in this browser.", true); }
      }));
      if ($("#drawer-propose")) $("#drawer-propose").addEventListener("click", async () => { if (await propose(act, [e.EXC_ID])) { openTxn(id); route(); } });
    } catch (err) { body.innerHTML = `<div class="error-box">${esc(err.message)}</div>`; }
  }
  function closeDrawer() {
    if (!$("#drawer").classList.contains("open")) return;
    $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; document.body.classList.remove("drawer-open");
    if (state.lastFocus && state.lastFocus.isConnected) state.lastFocus.focus();
    const { page, params } = parseHash();
    if (params.open) { delete params.open; history.replaceState(null, "", `#/${page}${Object.keys(params).length ? "?" + new URLSearchParams(params) : ""}`); }
  }
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape") { if ($("#drawer").classList.contains("open")) closeDrawer(); else if (tour.i >= 0) tour.stop(); } });

  // ------------------------------------------------------------------ guided demo: walks the real pages, reads live figures, never writes
  const tour = {
    steps: null, i: -1,
    async start() {
      try {
        const [o, q] = await Promise.all([call("/api/overview"), call(`/api/queue?focus=${encodeURIComponent(state.meta.queue_focus[0])}&sort=${encodeURIComponent(state.meta.queue_sorts[0])}&size=${Math.min(...state.meta.page_sizes)}`)]);
        this.steps = this.build(o, q.rows[0]);
        document.body.classList.add("touring");
        this.show(0);
      } catch (e) { toast(`The guided demo needs the database: ${esc(e.message)}`, true); }
    },
    build(o, topCase) {
      const k = o.kpi, v = o.volume, r = ruleParts(o.rules), h = state.health;
      const steps = [
        { page: "home", spot: "#home-hero", t: "The problem", b: `The customer was debited but the payment failed. The deadline is ${r.deadlines}, then the bank owes ${r.rate}, without waiting for a complaint.` },
        { page: "connect", spot: "#lineage", t: "Where the data comes from", b: `${esc(o.dataset.name)} sits in Exasol. Every number is a live query on it, and you can import other data here.` },
        { page: "dashboard", spot: "#today-cost", t: "What costs money tomorrow", b: `If nothing changes, ${plural(k.ACCRUING_N, "case")} add ${fmt.rs(k.NEW_ACCRUAL_RS)} tomorrow. The list beside it says what to do, in order.` },
        { page: "queue", params: { focus: state.meta.queue_focus[0] }, spot: "#queue-table", t: "The work, in order", b: "Compensation is a flat amount a day, so every accruing case costs the same to leave open. The customers waiting longest come first." },
      ];
      if (topCase) steps.push({ page: "queue", params: { focus: state.meta.queue_focus[0], open: topCase.EXC_ID }, t: "One case, three systems", b: "The next step comes first, then the clock, then what the switch, NPCI and core banking each recorded." });
      steps.push(
        { page: "assistant", spot: "#suggest", t: "Ask in plain words", b: "Press a question. The assistant reads through the Exasol MCP server as a read-only user, and every query is shown." },
        { page: "actions", spot: "#actions-list", t: "Nothing moves without a person", b: `Proposals wait here.${state.meta.maker_checker ? " Nobody can approve their own." : ""} Approving runs a fixed SQL template and re-runs the reconciliation.` },
        { page: "audit", spot: "#audit-table", t: "The proof", b: "Who approved, when, the exact SQL that ran, and the numbers before and after." },
        { page: "sources", spot: "#source-cards", t: "Where it all runs", b: `${fmt.n(v.TXNS)} ${o.dataset.source === "sample" ? "synthetic " : ""}transactions from three sources${isNum(o.recon_ms) ? `, reconciled in ${seconds(o.recon_ms)}` : ""}${h ? ` on Exasol ${esc(String(h.version).split("-")[0])}` : ""}.` });
      return steps;
    },
    show(i) {
      this.i = i;
      const s = this.steps[i], hash = href(s.page, s.params || {});
      closeDrawer();
      if (location.hash === hash) route(); else location.hash = hash;
    },
    paint() {    // called at the end of every route while the tour runs
      if (this.i < 0) return;
      const s = this.steps[this.i], last = this.i === this.steps.length - 1;
      $$(".tour-spot").forEach(el => el.classList.remove("tour-spot"));
      const spot = s.spot && $(s.spot);
      if (spot) { spot.classList.add("tour-spot"); if (spot.getBoundingClientRect().height < innerHeight * .6) spot.scrollIntoView({ block: "center", behavior: "smooth" }); }
      const c = $("#coach");
      c.hidden = false;
      c.innerHTML = `<div class="coach-top"><div class="coach-dots">${this.steps.map((_, n) => `<i class="${n <= this.i ? "on" : ""}"></i>`).join("")}</div>
          <span>Step ${this.i + 1} of ${this.steps.length}</span><button class="x" id="coach-x" type="button" aria-label="End the guided demo"><i data-lucide="x"></i></button></div>
        <h3>${esc(s.t)}</h3><p>${s.b}</p>
        <div class="coach-acts"><span class="coach-keys">← → to move · Esc to leave</span><div class="row">
          ${this.i ? `<button class="btn on-dark" id="coach-back" type="button"><i data-lucide="arrow-left"></i>Back</button>` : ""}
          <button class="btn gold" id="coach-next" type="button">${last ? "Finish" : "Next"}${last ? "" : `<i data-lucide="arrow-right"></i>`}</button></div></div>`;
      icons(c);
      $("#coach-x").addEventListener("click", () => this.stop());
      $("#coach-next").addEventListener("click", () => this.next());
      if ($("#coach-back")) $("#coach-back").addEventListener("click", () => this.back());
    },
    next() { if (this.i === this.steps.length - 1) { this.stop(); go("home"); } else this.show(this.i + 1); },
    back() { if (this.i > 0) this.show(this.i - 1); },
    stop() {
      this.i = -1;
      $("#coach").hidden = true;
      document.body.classList.remove("touring");
      $$(".tour-spot").forEach(el => el.classList.remove("tour-spot"));
    },
  };
  document.addEventListener("click", e => { if (e.target.closest("[data-tour-start]") && tour.i < 0) tour.start(); });
  document.addEventListener("keydown", e => {
    if (tour.i < 0 || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === "ArrowRight") tour.next();
    if (e.key === "ArrowLeft") tour.back();
  });

  // ------------------------------------------------------------------ boot
  who.render();
  icons();
  loadShell();
  call("/api/overview").then(setContext).catch(() => { /* shown per page */ });
  // pages build their menus from /api/meta (no database needed), so it loads before the first render
  call("/api/meta").then(m => { state.meta = m; route(); })
    .catch(e => { $("#app").innerHTML = `<div class="error-box">Cannot reach the TAT Guard server: ${esc(e.message)}</div>`; });
})();
