# RESOURCES — what we import, and why

Every external resource goes through `05_RESOURCE_IMPORTER.md` §2. Machine-readable pins are in `sources.lock.json` and `import/repos.lock.jsonl`.

| Resource | Purpose | Publisher | Licence (as read) | Pin | Personal data? | Decision |
|---|---|---|---|---|---|---|
| https://github.com/exasol/mcp-server | Agent ↔ DB via MCP | Exasol (official) | MIT (`LICENSE`: "MIT License, Copyright (c) 2025 Exasol") | `2dd3ab9` | No | **Accept**, reference clone, used as a pip/uv dependency, not vendored |
| https://github.com/exasol/pyexasol | Python connector | Exasol (maintainer since 2023, per README) | MIT (`LICENSE.txt`: "MIT License, Copyright (c) 2022 Vitaly Markov") | `0d5adac` | No | **Accept**, pip dependency |
| https://github.com/exasol-labs/exasol-agent-skills | Correct Exasol usage hints | Exasol Labs | MIT (`LICENSE`: "MIT License, Copyright (c) 2026 Exasol AG") | `b355ba1` | No | **Accept**, read only; README not read yet |
| https://github.com/exasol-labs/exapump | Bulk load | Exasol Labs | MIT (`LICENSE`: "MIT License, Copyright (c) 2026 Exasol AG") | `d32ff2b` | No | **Accept**, pending a README read in Phase 1 |
| https://github.com/exasol/transformers-extension | Optional NER | Exasol (official) | MIT (`LICENSE`: "MIT License, Copyright (c) 2022 Exasol") | `90b17fc` | No | **Accept** (stretch only) |
| https://www.npmjs.com/package/lucide (v1.47.0) | UI icons | Lucide Icons and Contributors | ISC (`LICENSE` copied to `ui/static/vendor/lucide-1.47.0/`; permissive, MIT-equivalent) | npm tarball, sha512 integrity verified | No | **Accept**, vendored (one minified file + licence) |
| Inter via fonts.googleapis.com | UI typeface | Rasmus Andersson / Google Fonts | SIL OFL 1.1 (per Google Fonts) | linked, not pinned | No | **Accept**, link-only; system-font fallback offline |

Not yet evaluated (listed in 05 §3–§5): exasol-labs-text2sql-mcp-server, ai-lab, script-languages-release, sqlalchemy-exasol, docker-db, Splink, AgamiAI/Indian-Bank-Statements, the India Data Portal NPCI dataset, and Kaggle datasets. Reference documents in 05 §4 have not been fetched yet (`import/fetch_docs.py` not written or run).
