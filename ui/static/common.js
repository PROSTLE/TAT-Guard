// Shared by every page: the API call, DOM building (text goes in as text nodes, so nothing a visitor types can become
// markup), number formats, and the labels for every value the backend can send.

export async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function h(spec, props, ...kids) {
  const [tag, ...cls] = spec.split(".");
  const el = document.createElement(tag || "div");
  if (cls.length) el.className = cls.join(" ");
  if (props instanceof Node || typeof props !== "object" || Array.isArray(props) || props === null) {
    kids.unshift(props);
    props = {};
  }
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.classList.add(...String(v).split(/\s+/).filter(Boolean));
    else if (k in el && !["list", "form"].includes(k)) el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter(Boolean));
  return el;
}

const INT = new Intl.NumberFormat("en-IN");
const RS2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const n = (v) => (v === null || v === undefined || v === "" ? "–" : INT.format(Number(v)));
export function rs(v) {
  if (v === null || v === undefined || v === "") return "–";
  const x = Number(v);
  return `₹${Number.isInteger(x) ? INT.format(x) : RS2.format(x)}`;
}
export const plural = (count, word) => `${n(count)} ${word}${Number(count) === 1 ? "" : "s"}`;
export const paise = (v) => rs(Number(v) / 100);
export const secs = (ms) => (ms === null || ms === undefined ? "–" : Number(ms) >= 1000 ? `${(Number(ms) / 1000).toFixed(1)} s` : `${ms} ms`);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function day(v) {
  if (!v) return "–";
  const [y, m, d] = String(v).slice(0, 10).split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`;
}
export function when(v) {
  if (!v) return "–";
  const t = String(v).slice(11, 16);
  return t ? `${day(v)}, ${t}` : day(v);
}

export const CLASS_META = {
  DEBIT_NO_CREDIT: { label: "Debit, no credit", plain: "The customer was charged but the payment failed. The money must go back before the deadline.", tone: "red" },
  DUPLICATE_POSTING: { label: "Debited twice", plain: "One payment, two debits in the ledger. The customer is out of pocket by the second one.", tone: "red" },
  AMOUNT_MISMATCH: { label: "Wrong amount", plain: "The ledger debited a different amount from what the customer paid.", tone: "amber" },
  NPCI_SUCCESS_NO_CBS: { label: "Paid, never debited", plain: "The network says the payee was paid, but the ledger has no debit. The bank is out of pocket.", tone: "amber" },
  LATE_FILE: { label: "Waiting on late file", plain: "The NPCI file for this cycle has not arrived, so this cannot be confirmed yet. Probably not a real problem.", tone: "" },
  NPCI_MISSING: { label: "Missing at NPCI", plain: "The cycle's file has arrived but this payment is not in it.", tone: "amber" },
  UNMATCHED_CBS_DEBIT: { label: "Unmatched debit", plain: "A ledger debit no pass could tie to a payment. It needs a person.", tone: "amber" },
};
export const STATE_META = {
  OVERDUE: { label: "Overdue", tone: "red" },
  AT_RISK: { label: "Due today", tone: "amber" },
  WITHIN_TAT: { label: "Within deadline", tone: "green" },
  COMPENSATION_DUE: { label: "Compensation due", tone: "violet" },
  NO_TAT_CLOCK: { label: "No clock", tone: "" },
};
export const COMP_META = {
  NOT_DUE: "Not due", ACCRUING: "Building up", PAID: "Paid", UNDERPAID: "Underpaid", MISSING: "Missing",
};
export const ACTION_META = {
  POST_REVERSAL: { verb: "Propose reversal", label: "Reverse the debit" },
  PAY_COMPENSATION: { verb: "Propose compensation", label: "Pay compensation" },
  CHASE_SETTLEMENT_FILE: { verb: "Chase the file", label: "Chase settlement file" },
};
export const STATUS_TONE = {
  PROPOSED: "blue", APPROVED: "blue", EXECUTED: "green", LOGGED: "green", REJECTED: "", FAILED: "red",
};

export const CASE_LABEL = { UPI_P2P: "To a person", UPI_P2M: "To a merchant", IMPS: "IMPS" };
export const pill = (text, tone) => h(`span.pill${tone ? "." + tone : ""}`, text);
export const classLabel = (c) => CLASS_META[c]?.label || c;

let toastTimer;
export function toast(text, bad) {
  document.querySelector(".toast")?.remove();
  document.body.append(h(`div.toast${bad ? ".bad" : ""}`, { role: "status" }, text));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => document.querySelector(".toast")?.remove(), bad ? 6000 : 4200);
}

// The demo path: a small checklist that fills in as a visitor does each thing. Per browser, and fine to lose.
const PATH_KEY = "tg_path";
export const PATH = [
  { key: "caught", label: "Catch a failed payment", href: "#/live" },
  { key: "clock", label: "Move the clock", href: "#/live" },
  { key: "proposed", label: "Propose a fix", href: "#/cases" },
  { key: "approved", label: "Approve it as Vikram", href: "#/cases" },
  { key: "asked", label: "Ask the data a question", href: "#/ask" },
  { key: "proof", label: "Check the proof", href: "#/proof" },
];
export function pathDone() {
  try { return new Set(JSON.parse(localStorage.getItem(PATH_KEY) || "[]")); } catch { return new Set(); }
}
export function markPath(key) {
  const done = pathDone();
  if (done.has(key)) return;
  done.add(key);
  try { localStorage.setItem(PATH_KEY, JSON.stringify([...done])); } catch { /* the checklist is a convenience */ }
  document.dispatchEvent(new CustomEvent("tg:path"));
}
