# Changelog

All notable changes to TAT Guard will be documented in this file.

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
