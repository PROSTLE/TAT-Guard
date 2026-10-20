# TAT Guard

**Every stuck rupee, on a clock.**

TAT Guard reconciles UPI transactions across the NPCI settlement file, the bank's UPI switch log and the core-banking
(CBS) ledger inside **Exasol Personal**. It puts every failed-but-debited payment on the RBI turnaround-time (TAT)
clock and ranks the work queue by the rupees that will be owed tomorrow. An agent explains *why* breaks spiked,
reading only through the official Exasol MCP server, and can only **propose** fixes. A named human approves each one,
and every executed action lands in an audit log.

> **All data in this project is SYNTHETIC.** Our file layouts are stand-ins, not the real NPCI, switch or CBS
> formats (those are not public). Nothing here is real bank data or a statement about any real bank.

## Problem

> **Bank reconciliation teams** can't see which failed UPI debits are about to start costing money, **because**
> the evidence is split across three systems that must be matched transaction by transaction. Meanwhile the
> compensation clock keeps running. **If this worked,** they would see every stuck rupee ranked by what it will cost
> tomorrow, reverse the costliest first, and show that compensation was paid without the customer having to complain.
> (Template from the event page [EVT-PROBLEM-FORMAT].)

- **Rule:** if a UPI fund transfer leaves the customer debited but the beneficiary is not credited, the reversal is
  due by T+1 [RBI-TAT-UPI-P2P]. For a UPI merchant payment it is due by T+5 [RBI-TAT-UPI-P2M]. Beyond that the
  customer is owed ₹100 per day [RBI-TAT-COMP], paid suo moto, without a complaint [RBI-TAT-SUOMOTO]. T is the
  calendar date of the transaction [RBI-TAT-DAYCOUNT]. Source: RBI circular [RBI-TAT-REF].
- **Who:** the operations and reconciliation teams of banks that process UPI payments.
- **Scale:** UPI handled 24.07 bn transactions in Sept 2026, about 802 million a day [UPI-SEP26] (secondary source).
- **Impact (illustrative, not measured):** if 0.01% of daily UPI transactions ended debited-not-credited and 5% [ASSUMPTION]
  of those missed TAT by one day, compensation would be about ₹4.0 lakh a day, or ₹14.6 crore a year [ASSUMPTION]. Both rates
  are our assumptions, not data. Recompute with `python crosscheck/recompute_numbers.py`.

## What it does

1. **Synthetic data with ground truth.** `generator/generate.py` writes the three sources, a settlement-file arrival
   log and a ground-truth table. It injects six break types, including a late settlement file. The output is
   deterministic: the same seed gives byte-identical files.
2. **Reconciliation in Exasol.** There are four matching passes: transaction-id join, RRN + time window, a **Python UDF**
   (`RECON.EXTRACT_REF`) that pulls the reference out of messy CBS narrations, and fuzzy scoring for debits with no
   reference. These are followed by classification into `RECON.EXCEPTIONS`.
3. **TAT clock and ₹ exposure.** `RECON.PENALTY_EXPOSURE` computes the deadline, the penalty so far, the amount owed
   tomorrow and the suo-moto compensation status (PAID / UNDERPAID / MISSING). TAT days and ₹/day are loaded from
   `facts.yaml`, never typed into SQL.
4. **Agent, read-only through MCP.** Questions are answered by deterministic SQL playbooks (root cause, exposure,
   compensation), or by Google Gemini when `GEMINI_API_KEY` is configured. Every number in an answer must appear in that turn's
   query results; a grounding guard enforces this.
5. **Human-approved actions.** The agent can only create `PROPOSED` rows. A named human approves; the backend runs a
   fixed SQL template, re-runs the reconciliation and writes `AUDIT.ACTION_LOG` with the SQL and before/after values.

## Architecture

```
 generator/generate.py ──► data/*.csv (SYNTHETIC) ──► recon/pipeline.py load ──►  RAW.*  (Exasol Personal)
                                                                                   │
            sql/10_match_pass1..4 (SQL + Python UDF) ─► sql/15_classify ─► RECON.EXCEPTIONS
                                                                                   │
            sql/30_penalty_view: RECON.PENALTY_EXPOSURE, RECON.WORK_QUEUE  ◄── RECON.TAT_RULES ◄── facts.yaml
                                                                                   │
 ui/server.py (127.0.0.1) ── dashboard reads ──► read-only DB user (SELECT on RAW, RECON, AUDIT only)
     │  /api/meta: states, sorts, action types/statuses, sample questions (app.js holds labels only;
     │             tests/test_ui_contract.py fails if page and server drift apart)
     │  /api/ask ──► agent/agent.py ──► agent/mcp_reader.py ──► exasol-mcp-server 2.2.0 (read query only)
     │                     └── grounding_guard: every number must be in this turn's results
     │  /api/propose, /api/actions/<id>/approve ──► agent/actions.py (admin connection)
     │        PROPOSED ─► human APPROVE ─► fixed SQL template ─► recon re-run ─► AUDIT.ACTION_LOG
 VERIFIER.GROUND_TRUTH: read only by verify/ (the agent's DB user has no access)
```

## Quick start

Full steps, troubleshooting and the demo script are in [docs/DEPLOY.md](docs/DEPLOY.md). In short:
`exasol install local` → `exasol slc install PYTHON3` → `pip install -r requirements.txt` → fill `.env` from