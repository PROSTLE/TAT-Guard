# Changelog

All notable changes to TAT Guard will be documented in this file.

## [Unreleased] - 2026-10-31

Commit dates in this repository's history do not show when the work was done. Work began on 2026-10-07, inside the
challenge window: see the date-stamped files in `reports/`.

### Fixed
- Queue rank: what a case adds tomorrow first, then the longest wait; it used to rank by running total, which is sunk cost
- A partial reversal no longer stops the TAT clock; a reversal posts only what is still outstanding
- A double debit on a failed payment keeps its TAT clock instead of becoming DUPLICATE_POSTING
- A failed recon after a posting can no longer lead to a second posting
- Grounding guard refuses spelled-out numbers, lakh/crore shorthand and date digits reused as amounts
- CI: Python 3.12 and 3.13, the versions the pinned dependencies support
- Event dates in facts.yaml

### Changed
- UI redesign: Home intro page, sidebar grouped by job (Act, Understand, Prove), a short Today page in place of the 13-card dashboard, Insights with one topic at a time, light and dark themes, plain empty states
- README rewritten around who it is for and how it works, with diagrams; results, safety and limitations unchanged
- Break types are a ranked bar list; a donut could not show one type at 96% of exceptions

### Added
- TAT Guard logo and favicon on a transparent background
- Connect & Import: pick an Exasol database, load the sample dataset, four CSV files or a schema, and watch the real load and reconciliation timings
- The data label follows what is loaded, and a strip shows where the data on the screens comes from
- Guided demo: nine steps through the real pages, using live figures, writing nothing
- Find a payment by UPI id or RRN from any page
- Maker-checker: the proposer of an action cannot approve it
- Dashboard: what needs doing, open cases by age, chase list by payee bank, compensation register with CSV export
- Queue: "Adding cost tomorrow" view, deadline countdown, payee-bank filter, ranking explained on the page
- Case drawer: one-line next step, copy buttons; Actions: what approving will post
- Accessibility: WCAG AA text contrast, keyboard row access, focus handling, skip link, reduced motion
- `verify/v5_edge_cases.py`: cases the generator never makes, through the real SQL
- `crosscheck/benchmark.py`: the same reconciliation in pandas and Exasol

### Removed
- Dockerfile: the app binds to 127.0.0.1 and needs Exasol, so the image could not serve anything
- External font request: the UI now loads nothing from outside this machine

## [0.1.0] - 2026-10-22

### Added
- Four-pass matching engine (exact TxnID, RRN+window, UDF narration, fuzzy)
- Break classification into RECON.EXCEPTIONS
- TAT clock and penalty exposure view
- Deterministic agent with SQL playbooks
- Gemini-backed agent mode (optional)
- Human-approved action system with audit logging
- Web dashboard with 8 pages
- Synthetic data generator with ground truth
- V0-V4 verification suite
- Cross-check modules (dual impl, penalty, number recompute)
- Claim scanner for fact-ID enforcement

### Security
- Agent runs through MCP with SELECT-only access
- Grounding guard rejects unverified numbers
- Actions use fixed SQL templates, not LLM-generated SQL
- Human approval required for all state changes
