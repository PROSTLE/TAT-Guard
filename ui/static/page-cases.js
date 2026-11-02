// Cases: the ranked work, one case with the evidence behind it, and the maker-checker flow.
import { api, h, clear, n, rs, secs, day, when, pill, toast, classLabel, markPath, CASE_LABEL, CLASS_META, STATE_META, COMP_META, ACTION_META, STATUS_TONE } from "./common.js";
import { ctx } from "./app.js";

const TABS = [
  { key: "accruing", label: "Adding cost tomorrow", q: { focus: "accruing" } },
  { key: "OVERDUE", label: "Overdue", q: { state: "OVERDUE" } },
  { key: "AT_RISK", label: "Due today", q: { state: "AT_RISK" } },
  { key: "WITHIN_TAT", label: "Within deadline", q: { state: "WITHIN_TAT" } },
  { key: "COMPENSATION_DUE", label: "Compensation due", q: { state: "COMPENSATION_DUE" } },
  { key: "NO_TAT_CLOCK", label: "No clock", q: { state: "NO_TAT_CLOCK" } },
  { key: "all", label: "All", q: {} },
];
const SIZE = 25;

export function casesPage(root, params) {
  let tab = "accruing";
  let page = 1;
  let search = "";
  let cls = "";
  let selected = null;
  let drawer = null;
  let waitingDecision = null;

  const tabsEl = h("div.tabs", { role: "group", "aria-label": "Which cases" });
  const searchEl = h("input", { type: "text", placeholder: "Search by UPI id or RRN", "aria-label": "Search", oninput: debounce(() => { search = searchEl.value.trim(); page = 1; load(); }) });
  const clsEl = h("select", { "aria-label": "Break type", onchange: () => { cls = clsEl.value; page = 1; load(); } });
  const exportEl = h("a.btn.small", { href: "/api/queue.csv" }, "Export");
  const timing = h("span");
  const tableBody = h("tbody");
  const pager = h("div.pager");
  const approvals = h("div");

  clear(root,
    h("div.page-head", {}, h("h1", "Cases"), h("p", "Ranked by what a case adds to the bill tomorrow, then by who has waited longest. Click a case to see the evidence.")),
    h("div.cases", {},
      approvals,
      h("section.panel", {}, tabsEl,
        h("div.tools", {}, searchEl, clsEl, h("div.right", {}, timing, exportEl)),
        h("div.scroll", {}, h("table.tbl", {},
          h("thead", {}, h("tr", {}, h("th.r", "#"), h("th", "Payment"), h("th.r", "Amount"), h("th", "What happened"), h("th", "Clock"), h("th.r", "Adds tomorrow"))),
          tableBody)),
        pager)));

  function debounce(fn) {
    let t;
    return () => { clearTimeout(t); t = setTimeout(fn, 320); };
  }

  function drawTabs(data) {
    const count = (key) => (key === "accruing" ? data.accruing : key === "all" ? Object.values(data.tabs).reduce((a, b) => a + Number(b), 0) : data.tabs[key] ?? 0);
    clear(tabsEl, TABS.map((t) => h("button", {
      "aria-pressed": String(t.key === tab), onclick: () => { tab = t.key; page = 1; load(); },
    }, t.label, h("span.n", n(count(t.key))))));
  }

  async function load() {
    const q = TABS.find((t) => t.key === tab).q;
    const qs = new URLSearchParams({ ...q, page, size: SIZE });
    if (search) qs.set("q", search);
    if (cls) qs.set("class", cls);
    try {
      const data = await api(`/api/queue?${qs}`);
      exportEl.href = `/api/queue.csv?${new URLSearchParams({ ...q, ...(cls ? { class: cls } : {}) })}`;
      timing.textContent = `${n(data.total)} cases, read in ${secs(data.ms)}`;
      drawTabs(data);
      clear(clsEl, h("option", { value: "" }, "All break types"), data.classes.map((c) => h("option", { value: c, selected: c === cls }, classLabel(c))));
      clear(tableBody, data.rows.map(row));
      if (!data.rows.length) clear(tableBody, h("tr", {}, h("td", { colSpan: 6 }, h("div.empty", "Nothing here right now."))));
      const pages = Math.max(1, Math.ceil(data.total / SIZE));
      clear(pager, h("span", `Page ${n(page)} of ${n(pages)}`), h("div.right", {},
        h("button.btn.small", { disabled: page <= 1, onclick: () => { page -= 1; load(); } }, "Previous"),
        h("button.btn.small", { disabled: page >= pages, onclick: () => { page += 1; load(); } }, "Next")));
    } catch (e) {
      toast(e.message, true);
    }
  }

  function clock(r) {
    const meta = STATE_META[r.TAT_STATE];
    const d = Number(r.DAYS_TO_DEADLINE);
    let sub = "";
    if (r.TAT_STATE === "OVERDUE") sub = `${n(-d)} days past ${day(r.DEADLINE_DT)}`;
    else if (r.TAT_STATE === "AT_RISK") sub = `Reverse by ${day(r.DEADLINE_DT)}`;
    else if (r.TAT_STATE === "WITHIN_TAT") sub = `Deadline ${day(r.DEADLINE_DT)}`;
    else if (r.TAT_STATE === "COMPENSATION_DUE") sub = `${rs(r.COMP_GAP_RS)} owed`;
    return [pill(meta.label, meta.tone), sub ? h("div.sub", sub) : null];
  }

  function row(r) {
    const added = Number(r.NEW_ACCRUAL_RS);
    return h(`tr.click${selected === r.EXC_ID ? ".sel" : ""}`, { onclick: () => openCase(r.EXC_ID) },
      h("td.r.faint", n(r.QUEUE_RANK)),
      h("td", {}, h("div.mono", r.UPI_TXN_ID || r.CBS_ENTRY_ID || r.RRN), h("div.sub", `${r.TXN_TYPE || "Unmatched"} · ${when(r.TXN_TIME)}`)),
      h("td.r", rs(r.AMOUNT_RS)),
      h("td", classLabel(r.CLASS)),
      h("td", clock(r)),
      h("td.r", added > 0 ? h("div", {}, h("b", `+${rs(added)}`), h("div.sub", `${rs(r.ACCRUED_RS)} so far`)) : h("span.faint", "–")));
  }

  // ---- one case
  async function openCase(id) {
    selected = id;
    let d;
    try {
      d = await api(`/api/txn?id=${encodeURIComponent(id)}`);
    } catch (e) {
      return toast(e.message, true);
    }
    closeDrawer();
    drawer = h("aside.drawer", { "aria-label": "Case details" }, caseView(d));
    document.body.append(drawer);
    load();
  }
  function closeDrawer() {
    drawer?.remove();
    drawer = null;
  }

  function nextStep(d) {
    const e = d.exception;
    const p = d.penalty;
    const q = d.queue;
    if (!e) return { text: "This payment reconciled cleanly. Nothing to do.", tone: "green" };
    if (!q) return { text: "This case is closed: the debit was reversed and any compensation paid.", tone: "green" };
    if (q.TAT_STATE === "OVERDUE") return { text: `Reverse now. This case is ${n(p.PENALTY_DAYS)} days overdue. ${rs(p.PENALTY_RS)} has built up and ${rs(p.NEW_ACCRUAL_RS)} more is added tomorrow.`, tone: "red" };
    if (q.TAT_STATE === "AT_RISK") return { text: `Reverse today. From tomorrow this case costs ₹100 a day.`, tone: "amber" };
    if (q.TAT_STATE === "WITHIN_TAT") return { text: `The customer's money must be back by ${day(p.DEADLINE_DT)}. Nothing is owed yet.`, tone: "" };
    if (q.TAT_STATE === "COMPENSATION_DUE") return { text: `The money went back late, so ${rs(p.COMP_GAP_RS)} of compensation is owed, without the customer having to ask.`, tone: "amber" };
    return { text: CLASS_META[e.CLASS]?.plain || "", tone: "" };
  }

  function actionArea(d) {
    const e = d.exception;
    const pendingRow = (d.actions || []).find((a) => a.STATUS === "PROPOSED");
    const role = ctx.session.persona.role;
    if (pendingRow) {
      const who = String(pendingRow.CREATED_BY).replace("analyst:", "").replace("agent:gemini", "the AI analyst").replace("agent:deterministic", "the assistant");
      return role === "approver"
        ? h("div.acts-row", {}, h("button.btn.good", { onclick: () => decide(pendingRow.ACTION_ID, true) }, `Approve ${ACTION_META[pendingRow.ACTION_TYPE].label.toLowerCase()}`),
          h("button.btn.danger", { onclick: () => decide(pendingRow.ACTION_ID, false) }, "Reject"), h("span.faint", `Proposed by ${who}`))
        : h("div.acts-row", {}, pill("Waiting for approval", "blue"), h("span.faint", `Proposed by ${who}. Switch to ${ctx.session.personas.approver.name} to approve it.`));
    }
    const action = d.queue?.PROPOSE_ACTION;
    if (!action || !e) return null;
    return role === "analyst"
      ? h("div.acts-row", {}, h("button.btn.primary", { onclick: () => propose(action, e.EXC_ID) }, ACTION_META[action].verb), h("span.faint", "A second person must approve it."))
      : h("span.faint", `Switch to ${ctx.session.personas.analyst.name} to propose a fix. Approvers cannot raise their own.`);
  }

  async function propose(action, id) {
    try {
      const out = await api("/api/propose", { action_type: action, target_ref: id });
      const r = out.results[0];
      if (r.error) return toast(r.error, true);
      markPath("proposed");
      toast(`Proposed. Switch to ${ctx.session.personas.approver.name} to approve it.`);
      openCase(id);
      drawApprovals();
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function decide(id, approve) {
    try {
      const job = await api(`/api/actions/${id}/${approve ? "approve" : "reject"}`, {});
      waitingDecision = { job: job.id, approve };
      toast(approve ? "Approved. Posting to the ledger, then reconciling everything." : "Rejected.");
    } catch (e) {
      toast(e.message, true);
    }
  }

  function caseView(d) {
    const e = d.exception || {};
    const s = d.state || {};
    const p = d.penalty;
    const next = nextStep(d);
    const amount = e.AMOUNT_RS ?? s.AMOUNT_RS;
    return [
      h("button.drawer-close", { "aria-label": "Close", onclick: closeDrawer }, "×"),
      h("h2", `${rs(amount)} · ${e.CLASS ? classLabel(e.CLASS) : "Clean payment"}`),
      h("div.mono.faint", e.UPI_TXN_ID || s.UPI_TXN_ID || e.CBS_ENTRY_ID),
      h(`div.next${next.tone ? "." + next.tone : ""}`, next.text),
      actionArea(d),
      p ? [h("h3", "The clock"), h("div.kv", {},
        kv("Rule", `${CASE_LABEL[p.CASE_NAME] || p.CASE_NAME}, T+${p.TAT_DAYS}`), kv("Deadline", day(p.DEADLINE_DT)), kv("Days late", n(p.PENALTY_DAYS)),
        kv("Built up", rs(p.PENALTY_RS)), kv("Owed tomorrow", rs(p.OWED_TOMORROW_RS)), kv("Compensation", `${COMP_META[p.COMP_STATUS]}${Number(p.COMP_GAP_RS) > 0 ? `, ${rs(p.COMP_GAP_RS)} short` : ""}`))] : null,
      h("h3", "What each system recorded"),
      source("UPI switch", d.switch, (r) => [`${r.STATUS} · ${rs(r.AMOUNT_RS)} · ${r.RESP_CODE}`, `${when(r.TXN_TIME)} · RRN ${r.RRN}`]),
      source("NPCI settlement", d.npci, (r) => [`${r.STATUS} · ${rs(r.AMOUNT_RS)} · payee ${r.PAYEE_BANK}`, `Settled ${day(r.SETTLEMENT_DT)}, cycle ${r.CYCLE_NO}`]),
      source("Core banking ledger", d.cbs, (r) => [`${r.DR_CR === "DR" ? "Debit" : "Credit"} · ${rs(r.AMOUNT_RS)} · ${r.KIND}${r.MATCH_PASS ? `, matched in pass ${r.MATCH_PASS}` : ""}`, r.NARRATION]),
      d.actions?.length ? [h("h3", "What was done"), d.actions.map((a) => h("div.src", {},
        h("div.acts-row", {}, pill(a.STATUS, STATUS_TONE[a.STATUS]), h("span", ACTION_META[a.ACTION_TYPE].label)),
        h("div.sub", `${a.CREATED_BY}${a.DECIDED_BY ? ` → ${a.DECIDED_BY}` : ""}`)))] : null,
    ];
  }

  function kv(label, value) {
    return h("div", {}, h("small", label), h("b", value));
  }
  function source(title, rows, fmt) {
    if (!rows?.length) return h("div.src", {}, h("strong", title), h("div.sub", "No record"));
    return rows.map((r) => {
      const [a, b] = fmt(r);
      return h("div.src", {}, h("strong", title), h("div", a), h("div.sub", b));
    });
  }

  // ---- approvals
  async function drawApprovals() {
    try {
      const data = await api("/api/actions?status=PROPOSED");
      if (!data.rows.length) return clear(approvals);
      const role = ctx.session.persona.role;
      clear(approvals, h("section.panel", {},
        h("header", {}, h("h2", `Waiting for approval (${n(data.rows.length)})`),
          h("span.right", role === "approver" ? "You see exactly what will be posted before you say yes." : `Switch to ${ctx.session.personas.approver.name} to decide these.`)),
        h("div.scroll", {}, h("table.tbl", {}, h("tbody", {}, data.rows.map((a) => h("tr.click", { onclick: () => openCase(a.TARGET_REF) },
          h("td", ACTION_META[a.ACTION_TYPE]?.label || a.ACTION_TYPE),
          h("td.r", a.POST_RS === null ? "–" : rs(a.POST_RS)),
          h("td.sub", a.RATIONALE),
          h("td.sub", String(a.CREATED_BY).replace("analyst:", "").replace("agent:gemini", "AI analyst").replace("agent:deterministic", "Assistant")),
          h("td.r", {}, role === "approver" ? h("div.acts-row", {},
            h("button.btn.small.good", { onclick: (ev) => { ev.stopPropagation(); decide(a.ACTION_ID, true); } }, "Approve"),
            h("button.btn.small.danger", { onclick: (ev) => { ev.stopPropagation(); decide(a.ACTION_ID, false); } }, "Reject")) : null))))))));
    } catch (e) {
      toast(e.message, true);
    }
  }

  load();
  drawApprovals();
  if (params.open) openCase(params.open);

  return {
    unmount() { closeDrawer(); },
    onParams(p) { if (p.open) openCase(p.open); },
    onPersona() {
      drawApprovals();
      if (selected && drawer) openCase(selected);
    },
    onPoll(st) {
      if (!waitingDecision) return;
      const job = st.mine.find((j) => j.id === waitingDecision.job);
      if (job?.state === "done") {
        const res = job.result || {};
        if (waitingDecision.approve && res.status === "EXECUTED") {
          markPath("approved");
          const b = res.before || {};
          const a = res.after || {};
          const moved = Number(b.new_accrual_24h_rs) !== Number(a.new_accrual_24h_rs);
          toast(moved ? `Posted. Adds tomorrow went from ${rs(b.new_accrual_24h_rs)} to ${rs(a.new_accrual_24h_rs)}. It is in the audit log.`
            : "Posted to the ledger and reconciled. It is in the audit log.");
        } else if (waitingDecision.approve) {
          toast(`Recorded as ${res.status}.`);
        }
        waitingDecision = null;
        load();
        drawApprovals();
        if (selected && drawer) openCase(selected);
      } else if (job?.state === "failed") {
        toast(job.error, true);
        waitingDecision = null;
        drawApprovals();
      }
    },
  };
}
