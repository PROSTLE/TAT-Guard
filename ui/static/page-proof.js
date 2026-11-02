// Proof: is it right, who did what, and where the money is stuck. Every figure is a live query.
import { api, h, clear, n, rs, secs, day, when, pill, toast, classLabel, markPath, ACTION_META, STATUS_TONE } from "./common.js";
import { ctx } from "./app.js";

function pct(a, b) {
  return b ? `${((100 * a) / b).toFixed(2)}%` : "–";
}

export function proofPage(root) {
  const scoreEl = h("div.panel-body", {}, h("div.empty", "Checking"));
  const auditEl = h("div");
  const whereEl = h("div.panel-body");
  const filesEl = h("div.scroll");
  const reportsEl = h("div.panel-body");
  const reportView = h("div");

  async function verify() {
    clear(scoreEl, h("div.empty", "Checking every break against the answer key"));
    try {
      const v = await api("/api/live/verify");
      const total = v.tp + v.fp + v.fn;
      markPath("proof");
      clear(scoreEl,
        h("div.score", {},
          h("div", {}, h("b", n(v.tp)), h("small", "breaks found correctly")),
          h("div", {}, h("b", n(v.fp)), h("small", "false alarms")),
          h("div", {}, h("b", n(v.fn)), h("small", "missed")),
          v.live_total ? h("div", {}, h("b", `${n(v.live_correct)} of ${n(v.live_total)}`), h("small", "live payments classified correctly")) : null),
        h("div.scroll", {}, h("table.tbl", {},
          h("thead", {}, h("tr", {}, h("th", "Break type"), h("th.r", "Found"), h("th.r", "False alarms"), h("th.r", "Missed"), h("th.r", "Precision"), h("th.r", "Recall"))),
          h("tbody", {}, v.classes.map((c) => h("tr", {}, h("td", classLabel(c.class)), h("td.r", n(c.tp)), h("td.r", n(c.fp)), h("td.r", n(c.fn)),
            h("td.r", pct(c.tp, c.tp + c.fp)), h("td.r", pct(c.tp, c.tp + c.fn))))))),
        h("p.prose", {}, `Compared just now in ${secs(v.ms)} with what was injected. The answer key sits in a schema the matcher and the AI cannot read. `,
          total ? "A perfect score here means the engine finds what this generator injects. It says nothing about real bank data." : ""));
    } catch (e) {
      clear(scoreEl, h("div.empty", e.message));
    }
  }

  async function audit() {
    try {
      const a = await api("/api/audit");
      clear(auditEl, a.rows.length ? h("div.scroll", {}, h("table.tbl", {},
        h("thead", {}, h("tr", {}, h("th", "When"), h("th", "Action"), h("th", "Proposed by"), h("th", "Approved by"), h("th", "Result"), h("th", "Evidence"))),
        h("tbody", {}, a.rows.map((r) => h("tr.logrow", {},
          h("td", when(r.EXECUTED)), h("td", ACTION_META[r.ACTION_TYPE]?.label || r.ACTION_TYPE),
          h("td", String(r.CREATED_BY).replace("analyst:", "").replace("agent:gemini", "AI analyst").replace("agent:deterministic", "Assistant")),
          h("td", r.EXECUTED_BY), h("td", pill(r.OUTCOME, STATUS_TONE[r.OUTCOME])),
          h("td", {}, h("details", {}, h("summary", "Exact SQL"), h("pre", r.EXECUTED_SQL)))))))) : h("div.empty", "Nothing has been approved yet. Propose a fix in Cases and approve it."));
    } catch (e) {
      clear(auditEl, h("div.empty", e.message));
    }
  }

  async function where() {
    try {
      const o = await api("/api/overview");
      const comp = o.compensation.filter((c) => c.COMP_STATUS !== "NOT_DUE");
      clear(whereEl,
        h("div.scroll", {}, h("table.tbl", {},
          h("thead", {}, h("tr", {}, h("th", "Payee bank to chase"), h("th.r", "Open"), h("th.r", "Overdue"), h("th.r", "Stuck"), h("th.r", "Adds tomorrow"))),
          h("tbody", {}, o.banks.map((b) => h("tr", {}, h("td", b.BANK), h("td.r", n(b.N)), h("td.r", n(b.OVERDUE_N)), h("td.r", rs(b.STUCK_RS)), h("td.r", rs(b.NEW_ACCRUAL_RS))))))),
        h("div.scroll", {}, h("table.tbl", {},
          h("thead", {}, h("tr", {}, h("th", "Compensation"), h("th.r", "Cases"), h("th.r", "Paid"), h("th.r", "Still owed"))),
          h("tbody", {}, comp.map((c) => h("tr", {}, h("td", c.COMP_STATUS), h("td.r", n(c.N)), h("td.r", rs(c.PAID_RS)), h("td.r", rs(c.GAP_RS)))))))
      );
    } catch (e) {
      clear(whereEl, h("div.empty", e.message));
    }
  }

  async function files() {
    try {
      const s = await api("/api/sources");
      const shown = s.files.filter((f) => f.FILE_STATUS !== "ON_TIME").concat(s.files.filter((f) => f.FILE_STATUS === "ON_TIME").slice(-4));
      clear(filesEl, h("table.tbl", {},
        h("thead", {}, h("tr", {}, h("th", "NPCI file"), h("th", "Expected"), h("th", "Arrived"), h("th.r", "Records"), h("th", "Status"))),
        h("tbody", {}, shown.map((f) => h("tr", {}, h("td", `${day(f.SETTLEMENT_DT)}, cycle ${f.CYCLE_NO}`), h("td", when(f.EXPECTED)), h("td", when(f.ARRIVED)),
          h("td.r", n(f.RECORD_COUNT)), h("td", pill(f.FILE_STATUS.replace("_", " ").toLowerCase(), f.FILE_STATUS === "NOT_ARRIVED" ? "red" : f.FILE_STATUS === "LATE" ? "amber" : "green")))))));
    } catch (e) {
      clear(filesEl, h("div.empty", e.message));
    }
  }

  async function reports() {
    try {
      const r = await api("/api/reports");
      const wanted = r.items.filter((i) => /^(verifier_V2_1000000|verifier_V4|verifier_V5|benchmark_1000000)/.test(i.name)).slice(0, 6);
      clear(reportsEl, h("p.prose", "Saved verification runs. These are the team's recorded results, not live figures."),
        h("div.chips", {}, wanted.map((i) => h("button.chip", {
          onclick: async () => {
            try {
              const t = await api(`/api/report?name=${encodeURIComponent(i.name)}`);
              clear(reportView, h("pre.mono", {}, t.text));
            } catch (e) { toast(e.message, true); }
          },
        }, i.name.replace(/_\d{8}T\d+\.md$/, "").replace("verifier_", "")))), reportView);
    } catch (e) {
      clear(reportsEl, h("div.empty", e.message));
    }
  }

  clear(root,
    h("div.page-head", {}, h("h1", "Proof"), h("p", "Can it be trusted? Check it yourself: these are computed now, on the same database, including anything you just did.")),
    h("div.proof", {},
      h("section.panel.span", {}, h("header", {}, h("h2", "Is it right?"), h("button.btn.small", { onclick: verify }, "Check again")), scoreEl),
      h("section.panel.span", {}, h("header", {}, h("h2", "Who did what"), h("span.right", "Every approved action, with the exact SQL that ran")), auditEl),
      h("section.panel", {}, h("header", {}, h("h2", "Where it is stuck"), h("a.btn.small", { href: "/api/compensation.csv" }, "Compensation register")), whereEl),
      h("section.panel", {}, h("header", {}, h("h2", "Settlement files")), filesEl),
      h("section.panel.span", {}, h("header", {}, h("h2", "Recorded test runs")), reportsEl),
      ctx.session.can_reset ? h("section.panel.span", {}, h("header", {}, h("h2", "Presenter"), h("span.right", "Only on the machine running the server")),
        h("div.panel-body", {}, h("button.btn.danger", {
          onclick: async () => {
            try {
              await api("/api/live/reset", {});
              toast("Resetting. The demo returns to the original dataset in about 20 seconds.");
            } catch (e) { toast(e.message, true); }
          },
        }, "Reset the demo"))) : null));

  verify();
  audit();
  where();
  files();
  reports();
  return {};
}
