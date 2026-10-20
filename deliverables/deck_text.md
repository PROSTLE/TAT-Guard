# TAT Guard: pitch deck source text

Source of truth for the slides. Tags stay here (04_NON_HALLUCINATOR §4); the rendered deck may hide them.
Run `python nonhalluc/claim_scan.py deliverables/deck_text.md` before every export.

## 1. TAT Guard: every stuck rupee, on a clock
ExaThon India 2026, Track 01. Reconciliation on Exasol Personal. All data shown is synthetic.

## 2. The rule
- A failed UPI fund transfer that left the customer debited must be reversed by T+1 [RBI-TAT-UPI-P2P]; a merchant payment by T+5 [RBI-TAT-UPI-P2M].
- After that the bank owes ₹100 per day [RBI-TAT-COMP], paid suo moto, without a complaint [RBI-TAT-SUOMOTO].
- UPI ran 24.07 bn transactions in Sept 2026 [UPI-SEP26]. At that scale, a small miss rate is a lot of customers.
- Footer: Source: RBI/2019-20/67 [RBI-TAT-REF] (TAT circular), "T is the day of transaction and refers to the calendar date" [RBI-TAT-DAYCOUNT]. Volume: startuptalky.com (secondary) [UPI-SEP26].

## 3. The problem
Bank reconciliation teams can't see which failed UPI debits are about to start costing money, because the evidence
is split across the NPCI settlement file, the UPI switch log and the core-banking ledger, and has to be matched
transaction by transaction. If this worked, they would see every stuck rupee ranked by what it costs tomorrow, fix
the costliest first, and show that compensation was paid.

## 4. What TAT Guard does
1. Reconciles the three sources inside Exasol: SQL joins, a Python UDF that reads references out of messy narrations, fuzzy matching.
2. Puts every debit-no-credit on the TAT clock and ranks the queue by rupees owed tomorrow.
3. Checks suo-moto compensation: paid, underpaid or missing.
4. Explains spikes: an agent runs read-only SQL through the official Exasol MCP server and shows every query.
5. Fixes only with a human: the agent proposes, a named person approves, everything is audited.

## 5. Architecture
Synthetic generator → RAW tables → four matching passes + Python UDF → EXCEPTIONS → PENALTY_EXPOSURE / WORK_QUEUE
(TAT rules loaded from facts.yaml) → UI. Agent → Exasol MCP server (SELECT only) → read-only DB user. Actions →
fixed SQL templates → recon re-run → ACTION_LOG.

## 6. Why Exasol
- The whole reconciliation is SQL plus an in-database Python UDF: data never leaves the database.
- Exasol Personal runs locally (Windows, Podman) with the official launcher; a Python script-language container enables the UDF.
- The agent uses Exasol's own MCP server, locked to SELECT and a read-only user.

## 7. Results (synthetic data, measured on our runs)
- 1M transactions: precision 1.0 and recall 1.0 for every break class; 46,618 exceptions identical in Exasol and in an independent pandas re-implementation [MEASURED].
- 10M transactions: overall precision 469,007 / 469,024; 3 wrong fuzzy matches and 7 ambiguous debits sent to a human [MEASURED].
- Penalty view equals the Python reference to the rupee: 966 cases at 1M and 9,409 at 10M, 0 differences [MEASURED].
- Recon time on a laptop: 16.9 s to 37.9 s at 1M (four runs) and 274 s at 10M [MEASURED]. Local preset only; no server hardware was measured.

## 8. An agent you can trust with a bank's data
- Read-only twice: the MCP server allows SELECT only, and the DB user has SELECT-only privileges.
- Every number in an answer must appear in that turn's query results; otherwise the raw results are shown.
- The agent can only propose. Approval needs a named human; the executed SQL and before/after values are logged.
- Verified: 8 of 9 safety checks pass; the 9th (Gemini mode) is blocked because no API key was available [MEASURED].

## 9. Demo
"Why did breaks spike?" → the agent finds a settlement file that never arrived (matches the injected ground truth) →
propose → approve the top reversal → the penalty clock stops → compensation becomes due → approve → audit log.

## 10. Impact (illustrative)
If 0.01% of daily UPI transactions ended debited-not-credited and 5% [ASSUMPTION] of those missed TAT by a day,
compensation would be about ₹4.0 lakh a day, or ₹14.6 crore a year [ASSUMPTION]. Both rates are assumptions, not data.

## 11. Limits and next steps
- Synthetic stand-in formats; real NPCI/CBS layouts are not public.
- Gemini mode written but not run; UI has no login; executed actions simulate the CBS posting.
- Next: cloud-preset benchmarks, real authentication, chargeback handling under NPCI's auto-acceptance rule [NPCI-OC213].

## 12. Thank you
Open source (MIT). Repository link: (add the public GitHub URL here before export).
