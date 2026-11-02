// Ask: a question in plain English, answered from the database, with every query on show.
import { api, h, clear, n, secs, toast, markPath } from "./common.js";
import { ctx } from "./app.js";

const AI_QUESTIONS = [
  "Why did breaks spike?",
  "Which payee bank should I chase first, and why?",
  "How much compensation have we paid late, and how much is still missing?",
  "Are merchant payments riskier than person-to-person ones here?",
  "What should I fix first today?",
];

function inline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index));
    const t = m[0];
    out.push(t.startsWith("**") ? h("b", t.slice(2, -2)) : h("code", t.slice(1, -1)));
    last = m.index + t.length;
  }
  out.push(text.slice(last));
  return out;
}

// A small subset of Markdown, built as DOM nodes: the model's text can never become markup.
function rendered(text) {
  const blocks = [];
  let list = null;
  for (const line of String(text).split("\n")) {
    const item = line.match(/^\s*[-*•]\s+(.*)/);
    if (item) {
      list = list || h("ul");
      list.append(h("li", {}, inline(item[1])));
      continue;
    }
    if (list) { blocks.push(list); list = null; }
    const clean = line.replace(/^#+\s*/, "").trim();
    if (clean) blocks.push(h("p", {}, inline(clean)));
  }
  if (list) blocks.push(list);
  return blocks;
}

function resultTable(r) {
  if (!r.rows?.length) return h("div.faint", "No rows");
  return h("div.results-tbl", {}, h("table.tbl", {},
    h("thead", {}, h("tr", {}, r.columns.map((c) => h("th", c)))),
    h("tbody", {}, r.rows.slice(0, 12).map((row) => h("tr", {}, row.map((v) => h("td", v === null ? "–" : String(v))))))));
}

function stepRow(s, i) {
  if (s.kind === "proposal") return h("div.faint", `Raised proposal ${s.action_id}`);
  if (s.kind === "note") return h("div.faint", s.text);
  return h("details.ask-step", {},
    h("summary", {}, s.error ? h("span.err", `Query ${i + 1} failed, the model will correct it`) : `Query ${i + 1}: ${n(s.rows)} rows in ${secs(s.ms)}`),
    h("pre", s.sql), s.error ? h("div.err", s.error) : null);
}

export function askPage(root) {
  const ai = () => ctx.session.ai;
  const thread = h("div");
  const notice = h("div");
  const input = h("textarea", {
    placeholder: "Ask anything about these payments", "aria-label": "Your question", maxLength: 2000,
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } },
  });
  const sendBtn = h("button.btn.primary", { onclick: () => send() }, "Ask");
  let active = null;

  function drawNotice() {
    const mode = ai().mode;
    clear(notice, mode === "gemini"
      ? null
      : h("div.notice", "No AI model is configured on this server, so only three prepared questions can be answered."));
  }

  function chips() {
    const qs = ai().mode === "gemini" ? AI_QUESTIONS : ctx.meta.suggestions;   // the prepared questions are all that works without a model
    return h("div.chips", {}, qs.map((q) => h("button.chip", { onclick: () => send(q) }, q)));
  }

  async function send(text) {
    const question = (text ?? input.value).trim();
    if (!question || active) return;
    input.value = "";
    const steps = h("div.ask-steps");
    const status = h("div.faint", "Thinking");
    const body = h("div");
    const turn = h("div.turn", {}, h("div.q", question), h("div.ans", {}, steps, status, body));
    thread.append(turn);
    turn.scrollIntoView({ block: "end" });
    sendBtn.disabled = true;
    try {
      const { id } = await api("/api/ask", { question });
      active = { id, steps, status, body, seen: 0 };
      watch();
    } catch (e) {
      status.textContent = e.message;
      sendBtn.disabled = false;
    }
  }

  async function watch() {
    if (!active) return;
    const a = active;
    try {
      const job = await api(`/api/ask/status?id=${a.id}`);
      while (a.seen < job.steps.length) {
        a.steps.append(stepRow(job.steps[a.seen], a.seen));
        a.seen += 1;
      }
      if (job.steps.length) a.status.textContent = "Reading the results";
      if (job.state === "running") { setTimeout(watch, 600); return; }
      finish(a, job);
    } catch (e) {
      a.status.textContent = e.message;
      active = null;
      sendBtn.disabled = false;
    }
  }

  function finish(a, job) {
    active = null;
    sendBtn.disabled = false;
    a.status.remove();
    if (job.state === "failed") return clear(a.body, h("p", `That did not work: ${job.error}`));
    const r = job.result;
    markPath("asked");
    const queries = r.queries || [];
    const proposal = r.proposal?.action_id;
    clear(a.body,
      r.fallback ? h("div.notice", r.fallback) : null,
      rendered(r.answer),
      proposal ? h("div.proposal", {}, `Proposed ${proposal}. Nothing has changed: a person must approve it in `, h("a", { href: "#/cases" }, "Cases"), ".") : null,
      r.proposal?.error ? h("div.notice", r.proposal.error) : null,
      queries.length ? h("details.ask-step", { open: Boolean(r.unsummarised) }, h("summary", `See the numbers (${n(queries.length)} ${queries.length === 1 ? "result" : "results"})`), queries.map(resultTable)) : null,
      h("div.ask-meta", {},
        h("span", r.mode === "gemini" && !r.fallback ? `Written by ${r.model || "the AI model"}` : "Prepared query"),
        h("span", "·"), h("span", r.grounded ? "Every number checked against the query results" : "Could not verify the numbers, showing raw results"),
        h("span", "·"), h("span", `${secs(job.result.total_ms)}`)));
    a.body.scrollIntoView({ block: "end" });
  }

  clear(root,
    h("div.ask", {},
      h("div.page-head", {}, h("h1", "Ask the data"),
        h("p", "The model writes SQL, runs it on Exasol as a read-only user, and answers from the results. It cannot change anything: it can only propose, and a person decides.")),
      notice, chips(), thread,
      h("div.ask-form", {}, input, sendBtn)));
  drawNotice();

  return {
    onPoll() {},
  };
}
