# Demo video script (≤ 3:00)

Written for the recorded submission video [EVT-DELIVERABLES]. Every number spoken is either a tagged fact or read
**off the screen** during recording ("[read from screen]"), so the script never states a figure that the live system
didn't produce. Before recording: reset the demo DB (docs/DEPLOY.md step 4), start `ui/server.py`, enter a name in
the header, and keep a terminal ready for `recon/pipeline.py recon`.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:25 | Title slide, then the README "Problem" section | "When a UPI payment fails but the customer is debited, the bank must reverse it by T+1 for fund transfers [RBI-TAT-UPI-P2P] and T+5 for merchant payments [RBI-TAT-UPI-P2M]. After that it owes ₹100 a day [RBI-TAT-COMP], suo moto, without waiting for a complaint [RBI-TAT-SUOMOTO]. Finding those cases means matching three systems, transaction by transaction. Everything you'll see runs on synthetic data." |
| 0:25–1:10 | Terminal: `python recon/pipeline.py recon` on the 1M dataset, step timings printing; then the UI "Last reconciliation run" panel | "This is Exasol Personal running locally. One command runs the whole reconciliation: joins, a Python UDF that pulls references out of messy ledger narrations, fuzzy matching, classification. The timer is real: [read TOTAL recon from screen] for a million transactions on this laptop." |
| 1:10–1:50 | UI: "What needs doing", then the work queue on "Adding cost tomorrow", then the compensation register | "The dashboard opens with what needs doing. Compensation is a flat amount a day, so every overdue case costs the same to leave open: [read top tile] tomorrow. The queue puts those first, longest wait first. And for cases already reversed, the register shows whether compensation was actually paid, with an export for the auditor: [read compensation tile]." |
| 1:50–2:30 | UI: click "Why did breaks spike?"; expand the queries; show the green "grounded" badge; open Actions panel | "Ask the agent why breaks spiked. It runs read-only SQL through the official Exasol MCP server, and every query is shown. The answer names the cause: a settlement file that never arrived for one cycle. Every number in that answer is checked against the query results before it's shown. The agent can't change anything. It proposed chasing the file, and that proposal waits for a human." |
| 2:30–3:00 | UI: ask "What should we fix first?", which proposes the rank 1 reversal → Actions shows what will be posted → Approve; after the recon re-runs, the audit log shows the SQL and the before→after; close on the repo URL | "The agent proposes the top reversal, and I see exactly what will be posted. I approve. Had I proposed it myself, a second person would have to. The backend runs a fixed, audited statement, re-runs the reconciliation, and the case stops accruing. Now it asks for the compensation that's due. Who, when, the exact SQL, before and after, all in the audit log. The data never leaves your own Exasol. The code is open source." |

Checklist before export: length ≤ 180 s (`ffprobe -v error -show_entries format=duration -of csv=p=0 demo.mp4`);
the SYNTHETIC DATA badge is visible in every UI shot; no real bank names or customer data appear.
