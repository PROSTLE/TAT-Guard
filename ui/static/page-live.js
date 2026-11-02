// Live: make a payment, choose what goes wrong, watch the three systems, the reconciliation and the verdict.
import { api, h, clear, n, rs, paise, secs, day, pill, toast, classLabel, markPath, pathDone, PATH, CLASS_META } from "./common.js";
import { ctx, moveClock } from "./app.js";

const NAMES = ["Ravi Kumar", "Meera Iyer", "Arjun Nair", "Fatima Shaikh", "Neha Joshi", "Imran Khan", "Divya Menon", "Karan Bedi"];
const SHOPS = ["Kirana Mart", "City Medicals", "Annapurna Stores", "Metro Fuels"];
const pick = (list) => list[Math.floor(Math.random() * list.length)];
const GROUPS = [
  ["Something breaks", ["debit_no_credit", "duplicate", "amount_mismatch", "no_debit"]],
  ["Nothing breaks, so it must stay clean", ["clean", "messy_narration", "no_reference", "switch_id_missing"]],
];

export function livePage(root) {
  const meta = ctx.meta.live;
  const scenarios = Object.fromEntries(meta.scenarios.map((s) => [s.key, s]));
  let chosen = "debit_no_credit";
  let type = "P2P";
  let jobId = null;
  let lastDone = null;

  // ---- form
  const payee = h("input", { type: "text", value: pick(NAMES), maxLength: 40, required: true, autocomplete: "off" });
  const amount = h("input", { type: "number", value: 1250, min: 1, max: meta.max_amount, step: "0.01", required: true });
  const bank = h("select", {}, meta.banks.map((b) => h("option", { value: b }, b)));
  bank.value = "BNK03";
  const typeSeg = h("div.seg", { role: "group", "aria-label": "Payment type" });
  const opts = h("div");
  const hint = h("p.hint");
  const pay = h("button.btn.primary.wide", { type: "submit" });

  function drawType() {
    clear(typeSeg, [["P2P", "To a person"], ["P2M", "To a merchant"]].map(([k, label]) => h("button", {
      type: "button", "aria-pressed": String(type === k),
      onclick: () => { type = k; payee.value = pick(k === "P2M" ? SHOPS : NAMES); drawType(); },
    }, label)));
  }
  function drawOpts() {
    clear(opts, GROUPS.map(([title, keys]) => [h("div.opt-group", title), keys.map((k) => h(`label.opt${chosen === k ? ".on" : ""}`, {},
      h("input", { type: "radio", name: "sc", value: k, checked: chosen === k, onchange: () => { chosen = k; drawOpts(); } }),
      h("span", scenarios[k].label)))]));
    hint.textContent = scenarios[chosen].hint;
    drawPay();
  }
  function drawPay() {
    pay.textContent = `Pay ${rs(amount.value || 0)}`;
  }
  amount.addEventListener("input", drawPay);

  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      pay.disabled = true;
      try {
        const job = await api("/api/live/pay", { payee: payee.value, amount: amount.value, txn_type: type, bank: bank.value, scenario: chosen });
        jobId = job.id;
        lastDone = null;
        drawJob(job);
      } catch (ex) {
        toast(ex.message, true);
      } finally {
        setTimeout(() => { pay.disabled = false; }, 900);
      }
    },
  },
  h("label.f", {}, h("span", "Pay to"), payee),
  h("div.row2", {}, h("label.f", {}, h("span", "Amount (₹)"), amount), h("label.f", {}, h("span", "Payee bank"), bank)),
  h("label.f", {}, h("span", "Payment type"), typeSeg),
  h("fieldset.fieldset", {}, h("legend", "What should happen?"), opts, hint),
  pay);

  // ---- bigger moves
  const stormRows = h("select", { "aria-label": "Payments in the outage" }, [10000, 50000, 100000, 200000].map((v) => h("option", { value: v }, `${n(v)} payments`)));
  const stormBank = h("select", { "aria-label": "Bank that goes down" }, meta.banks.map((b) => h("option", { value: b }, b)));
  stormBank.value = "BNK07";
  const stormBtn = h("button.btn.wide", { type: "button", onclick: startStorm }, "Start the outage");
  const stormNote = h("div.result-note.hidden");
  const fileBtn = h("button.btn.wide", { type: "button", onclick: deliverFile }, "Deliver the late file");
  const fileText = h("p");
  const fileNote = h("div.result-note.hidden");

  async function startStorm() {
    stormBtn.disabled = true;
    try {
      await api("/api/live/storm", { rows: Number(stormRows.value), fail_pct: 8, bank: stormBank.value });
      stormNote.classList.add("hidden");
      ctx.watchStorm = true;
    } catch (ex) {
      toast(ex.message, true);
    } finally {
      setTimeout(() => { stormBtn.disabled = false; }, 1500);
    }
  }
  async function deliverFile() {
    fileBtn.disabled = true;
    try {
      await api("/api/live/late-file", {});
      ctx.watchFile = true;
    } catch (ex) {
      toast(ex.message, true);
      fileBtn.disabled = false;
    }
  }

  const moves = h("section.panel", {},
    h("header", {}, h("h2", "Bigger moves")),
    h("div.big-move", {}, h("h3", "A late NPCI file"), fileText, fileBtn, fileNote),
    h("div.big-move", {}, h("h3", "A bank goes down"), h("p", "Generate an outage inside Exasol, in one SQL statement. 8% of these payments fail. Then ask the AI what happened."),
      h("div.row2.gap", {}, stormRows, stormBank), stormBtn, stormNote));

  // ---- result column
  const recSwitch = h("div.rec", {}, h("h3", "UPI switch"), h("div.none", "Waiting for a payment"));
  const recNpci = h("div.rec", {}, h("h3", "NPCI settlement"), h("div.none", "Waiting for a payment"));
  const recLedger = h("div.rec", {}, h("h3", "Core banking ledger"), h("div.none", "Waiting for a payment"));
  const stepList = h("div.steps");
  const runFoot = h("div.run-total");
  const runHint = h("span.right");
  const verdict = h("div");
  const pathEl = h("div.path");

  function drawPath() {
    const done = pathDone();
    clear(pathEl, PATH.map((p) => h(`a${done.has(p.key) ? ".done" : ""}`, { href: p.href }, p.label)));
  }

  function kv(pairs) {
    return h("dl", {}, pairs.flatMap(([k, v, cls]) => [h("dt", k), h("dd", cls ? { class: cls } : {}, v ?? "–")]));
  }
  function drawRecords(job) {
    const r = job.records;
    if (!r) return;
    const s = r.switch?.[0];
    const c = r.npci?.[0];
    const statusClass = (v) => (v === "SUCCESS" ? "good" : "bad");
    clear(recSwitch, h("h3", "UPI switch"), s ? kv([
      ["Status", s.STATUS, statusClass(s.STATUS)], ["Amount", paise(s.AMOUNT_PAISE)], ["Txn id", s.UPI_TXN_ID ?? "missing", s.UPI_TXN_ID ? "" : "bad"], ["RRN", s.RRN],
    ]) : h("div.none", "No row"));
    clear(recNpci, h("h3", "NPCI settlement"), c ? kv([
      ["Status", c.STATUS, statusClass(c.STATUS)], ["Amount", paise(c.AMOUNT_PAISE)], ["Payee bank", c.PAYEE_BANK], ["RRN", c.RRN],
    ]) : h("div.none", "No row"));
    const rows = r.ledger || [];
    clear(recLedger, h("h3", "Core banking ledger"), rows.length
      ? [rows.map((l, i) => kv([[i ? "Debit 2" : "Debit", paise(l.AMOUNT_PAISE), i ? "bad" : ""], ["Note", l.NARRATION]]))]
      : job.state === "reconciling" || job.state === "done"
        ? h("div.none", job.payment?.scenario === "no_reference" ? "No note carries this RRN. Pass 4 has to find the debit." : "No debit posted")
        : h("div.none", "Writing"));
  }

  function drawSteps(run, done) {
    const steps = run?.steps || meta.steps.map((s) => ({ ...s, state: "waiting" }));
    clear(stepList, steps.map((s) => h(`div.stepr.${done && s.state === "done" ? "done" : s.state}`, {},
      h("span.tick"), h("span", s.label),
      h("span.r", s.rows === null || s.rows === undefined ? "" : `${n(s.rows)} rows`),
      h("span.r", s.ms === null || s.ms === undefined ? "" : secs(s.ms)))));
    runHint.textContent = run?.state === "running" ? "Running now" : "";
    clear(runFoot, run?.total_ms
      ? [h("b", secs(run.total_ms)), h("span", `to reconcile all ${n(ctx.poll?.kpi?.TXNS)} payments, inside Exasol`)]
      : h("span", "Your payment is matched against every other payment, not on its own."));
  }

  function matchedBy(v) {
    const parts = [];
    if (v.match_pass) parts.push(`switch to NPCI in pass ${v.match_pass}`);
    if (v.cbs_pass) parts.push(`ledger to payment in pass ${v.cbs_pass}`);
    else parts.push("no ledger debit found");
    return `Matched ${parts.join(", ")}.`;
  }

  function drawVerdict(job) {
    if (!job) {
      return clear(verdict, h("div.empty", "Press Pay. The verdict comes from the reconciliation, which is never told what you chose."));
    }
    if (job.state === "failed") return clear(verdict, h("div.verdict.wrong", {}, h("h3", "That payment failed to run"), h("p", job.error)));
    if (job.state !== "done" || !job.verdict) {
      return clear(verdict, h("div.empty", job.state === "queued" ? "Waiting for the run in progress to finish." : "Reconciling. The verdict appears when Exasol finishes."));
    }
    const v = job.verdict;
    const meta2 = CLASS_META[v.class];
    const injected = v.expected ? classLabel(v.expected) : "no break";
    const found = v.class ? classLabel(v.class) : "no break";
    const stateTone = v.correct ? (v.class ? "caught" : "clean") : "wrong";
    const check = v.correct ? pill(`Correct: you injected ${injected.toLowerCase()}, Exasol found ${found.toLowerCase()}`, "green")
      : pill(`Mismatch: you injected ${injected.toLowerCase()}, Exasol found ${found.toLowerCase()}`, "amber");
    let body;
    if (v.class === "DEBIT_NO_CREDIT") {
      body = `${meta2.plain} Deadline ${day(v.deadline)} (T+${v.tat_days}), then ₹100 a day, whether or not the customer complains. Queue position ${n(v.rank)}.`;
    } else if (v.class) {
      body = `${meta2.plain} Queue position ${n(v.rank)}.`;
    } else {
      const how = { messy_narration: "The Python UDF pulled the reference out of the messy ledger note.", no_reference: "The note had no reference, so pass 4 matched the debit by score.", switch_id_missing: "The switch had no id, so pass 2 matched on RRN, amount and time." }[job.payment.scenario];
      body = how || "All three systems agree, so nothing was flagged.";
    }
    if (v.correct && v.class) markPath("caught");
    clear(verdict, h(`div.verdict.${stateTone}`, {},
      h("div.kicker", {}, h("span", v.class ? "Caught" : "No break"), check),
      h("h3", v.class ? classLabel(v.class) : "Clean payment"),
      h("p", body),
      h("p.faint", matchedBy(v)),
      h("div.acts", {},
        v.exc_id ? h("a.btn.primary", { href: `#/cases?open=${encodeURIComponent(v.exc_id)}` }, "Open this case") : null,
        v.class === "DEBIT_NO_CREDIT" ? h("button.btn", { onclick: () => moveClock(2) }, "Move the clock 2 days") : null)));
    verdict.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function drawJob(job) {
    if (job.records) drawRecords(job);
    drawVerdict(job);
  }

  function drawFile(k) {
    const f = k.MISSING_FILES?.[0];
    if (f) {
      fileText.textContent = `${n(f.BREAKS)} breaks are waiting on the NPCI file for ${day(f.SETTLEMENT_DT)}, cycle ${f.CYCLE_NO}. Deliver it and watch them clear.`;
      fileBtn.disabled = false;
    } else {
      fileText.textContent = "The file has arrived. Those breaks have cleared.";
      fileBtn.disabled = true;
    }
  }

  clear(root,
    h("div.page-head", {}, h("h1", "Make a payment fail. Watch Exasol catch it."),
      h("p", "This is a real Exasol database. Your payment becomes real rows, and the same reconciliation that handles every other payment decides what happened.")),
    pathEl,
    h("div.live", {},
      h("div", {},
        h("section.panel", {}, h("header", {}, h("span.step-n", "1"), h("h2", "Make a payment")), h("div.panel-body", {}, form)),
        moves),
      h("div", {},
        h("section.panel", {}, h("header", {}, h("span.step-n", "2"), h("h2", "What each system recorded")),
          h("div.panel-body", {}, h("div.records", {}, recSwitch, recNpci, recLedger))),
        h("section.panel", {}, h("header", {}, h("span.step-n", "3"), h("h2", "Exasol reconciles everything"), runHint),
          h("div.panel-body", {}, stepList, runFoot)),
        h("section.panel", {}, h("header", {}, h("span.step-n", "4"), h("h2", "The verdict")), verdict))));

  drawType();
  drawOpts();
  drawPath();
  drawSteps(null);
  drawVerdict(null);
  const onPath = () => drawPath();
  document.addEventListener("tg:path", onPath);

  return {
    unmount() { document.removeEventListener("tg:path", onPath); },
    onPoll(st) {
      drawFile(st.kpi);
      drawSteps(st.run || st.last_run, !st.run);
      const payments = st.mine.filter((j) => j.kind === "payment");
      const job = jobId ? payments.find((j) => j.id === jobId) : payments[payments.length - 1];
      if (job) {
        jobId = job.id;
        const stamp = `${job.id}:${job.state}`;
        if (stamp !== lastDone) {
          lastDone = stamp;
          drawJob(job);
        }
      }
      const storm = [...st.mine].reverse().find((j) => j.kind === "storm");
      if (ctx.watchStorm && storm?.state === "done") {
        ctx.watchStorm = false;
        stormNote.classList.remove("hidden");
        stormNote.textContent = `${n(storm.rows)} payments loaded and reconciled. ${n(storm.failed)} failed and are now on the clock. Ask the AI what happened.`;
      }
      const file = [...st.mine].reverse().find((j) => j.kind === "late_file");
      if (ctx.watchFile && file?.state === "done") {
        ctx.watchFile = false;
        fileNote.classList.remove("hidden");
        fileNote.textContent = `${n(file.rows)} NPCI records loaded. Breaks waiting on the file: ${n(file.before)} to ${n(file.after)}.`;
      } else if (ctx.watchFile && file?.state === "failed") {
        ctx.watchFile = false;
        toast(file.error, true);
      }
    },
  };
}
