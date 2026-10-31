# DEPLOY: run TAT Guard from scratch

This is the run guide. Every command below was run on Windows 11 (amd64) on 2026-10-11. The exception is the
macOS/Linux launcher line, which is quoted from the official Exasol Personal docs and was **not** run by us.
Why each step looks the way it does (with sources) is in [SETUP.md](SETUP.md).

> **Not yet done:** following this guide on a second, clean machine (02_CROSS_CHECK §5). Until someone does, treat
> any step that needed knowledge outside this file as a bug in this file.

## 0. Prerequisites

| Need | Version we used | Notes |
|---|---|---|
| Python | 3.13.5 | 3.12 or later: numpy 2.5.3 needs ≥ 3.12 |
| uv / uvx | 0.11.3 | runs the pinned Exasol MCP server in its own environment |
| Windows only: winget + WSL2 | WSL 2 | Exasol Personal runs in Podman's default machine on Windows |
| Free disk | ~1 GB per 1M rows of generated CSV + DB storage | 10M rows of CSV = 3.0 GB |

## 1. Exasol Personal (local)

**Windows:** download `exasol-personal_Windows_x86_64.zip` from the
[v2.3.0 release](https://github.com/exasol/exasol-personal/releases/tag/v2.3.0), check its SHA-256 against
`exasol-personal_2.3.0_checksums.txt`, unzip, then:

```powershell
.\exasol.exe install local                 # asks before installing/creating Podman's machine
# unattended (no terminal to answer prompts):  .\exasol.exe install local --auto-approve
.\exasol.exe slc install PYTHON3           # REQUIRED: local deployments ship without a Python UDF runtime
.\exasol.exe info                          # shows host 127.0.0.1, port 8563, user sys
```

**macOS / Linux** (official docs, not run by us): `curl https://downloads.exasol.com/exasol-personal/installer.sh | sh`,
then `exasol install local` and `exasol slc install PYTHON3`.

The initial local credentials are `sys` / `exasol`. Stop and start with `exasol stop` / `exasol start`; data survives.

## 2. Python environment

```powershell
cd tatguard
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## 3. Credentials

```powershell
Copy-Item .env.example .env      # then edit .env: admin password, a new agent password, host label
# load .env into this PowerShell session:
Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$($k.Trim())" $v.Trim() }
```
In bash: `set -a; . ./.env; set +a`. `.env` is git-ignored; never commit it.

## 4. Data, load, reconcile

```powershell
.\.venv\Scripts\python verify\v0_connect.py                                       # prints timestamp + server version
.\.venv\Scripts\python generator\generate.py --rows 1000000 --seed 42 --out data\1m   # SYNTHETIC data, ~1 min
.\.venv\Scripts\python recon\pipeline.py load --data data\1m
.\.venv\Scripts\python verify\v1_load.py --data data\1m                            # loads ground truth, checks counts
.\.venv\Scripts\python recon\pipeline.py recon
.\.venv\Scripts\python agent\setup_agent_user.py                                   # read-only DB user for the agent
```

## 5. Start the UI

```powershell
.\.venv\Scripts\python ui\server.py        # http://127.0.0.1:8765
```
The first start downloads the pinned `exasol-mcp-server==2.2.0` through uvx (a few seconds after that). **Assistant** →
*How it answers* shows deterministic playbooks unless `GEMINI_API_KEY` is set, in which case it shows Google Gemini.

The app opens on Home, with a **Guided demo** that walks the real pages and writes nothing. The sidebar groups the pages
by job: Act (Today, Work Queue, Approvals), Understand (Insights, Transactions, Assistant), Prove (Audit Log, Reports,
Data Sources). Every figure is a live query; clicking a KPI, a break type or a TAT status opens the matching filter in the Work Queue, and clicking
any row opens the transaction drawer (what the switch, NPCI and CBS each recorded, plus its TAT clock).

Demo flow: set your name (top right; it goes into the audit log) → **Assistant**: "Why did breaks spike?" → it
proposes chasing the late settlement file → ask **What is our ₹ exposure and what should we fix first?**, which proposes the
rank 1 reversal → **Approvals**: **Approve**, then confirm → the recon re-runs; the case becomes REVERSED and reappears
as *Compensation due* → propose that from the **Work Queue**, change the name at top right (nobody can approve their own
proposal), and approve it → it leaves the queue. Every step is in **Audit Log**, and
**Export CSV** on the Work Queue downloads the current filter.

**Connect & Import** does step 4 from the page: connect to an Exasol database (the password stays in the server's
memory), choose the sample dataset, four uploaded CSV files or a schema holding the four tables, and press **Import and
reconcile**. It runs the same `recon/pipeline.py` code, replaces all data in RAW and RECON, and logs the same timings.
CSV headers must match `sql/00_schemas.sql` exactly; these are stand-in layouts, so a real NPCI, switch or CBS file needs
converting first. Only public or synthetic data belongs here: there is no login. An import empties the ground truth, so
run `verify/v1_load.py --data data/1m` again before any `verify/` script. Uploads and schemas load into a staging schema and
are checked first, so a bad file leaves the current data alone.

The late file "arrives" with `.\.venv\Scripts\python recon\pipeline.py ingest-pending --data data\1m`.
To reset the demo, repeat the commands in step 4 from `pipeline.py load`, adding `--reset-audit` to the load to empty
the proposal and audit tables (they are append-only otherwise, so old actions would refer to data that was reloaded).

## 6. Verify (what the reports in `reports/` were produced with)

```powershell
.\.venv\Scripts\python -m pytest -q tests                                  # offline unit tests
.\.venv\Scripts\python verify\v1_generator.py                              # V1 generator gate
.\.venv\Scripts\python crosscheck\dual_impl.py --csv data\1m --exasol      # Exasol vs independent pandas matcher
.\.venv\Scripts\python crosscheck\penalty_check.py                         # penalty SQL vs penalty.py
.\.venv\Scripts\python verify\v4_agent.py --data data\1m                   # agent safety (creates/approves real actions)
.\.venv\Scripts\python verify\v5_edge_cases.py                             # edge cases through the real SQL (throwaway schemas)
.\.venv\Scripts\python crosscheck\benchmark.py --data data\1m               # same recon in pandas; about 17 min on our laptop
.\.venv\Scripts\python nonhalluc\claim_scan.py README.md                   # every number in README is sourced
.\.venv\Scripts\python crosscheck\recompute_numbers.py                     # recompute README numbers from facts.yaml
```
Run `dual_impl.py` right after `recon` (before any approvals or `ingest-pending`), because it compares against the
untouched CSVs.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No usable script language container is installed` | Run `exasol slc install PYTHON3` (step 1) |
| `podman machine init failed ... lookup quay.io: no such host` | Network/DNS was down; rerun `exasol install local` (it resumes) |
| New logins time out during a large `load` | The single-node DB is busy importing; wait for the load to finish |
| `insufficient privileges` in agent answers | Expected for anything outside RAW/RECON/AUDIT; re-run `agent/setup_agent_user.py` after a fresh DB |
| UI says `agent error` | Hover the badge; usually `TATGUARD_AGENT_PASSWORD` missing or `uvx` not on PATH |
| `WinError 10061` / connection refused on 8563, although `exasol info` says `running` | After a Windows reboot Podman's machine is stopped and `exasol info` still shows the last known state. Run `podman machine start`, then `exasol start` (seen 2026-10-18) |
| UI returns `403 request not from the TAT Guard page` | Open the UI as `http://127.0.0.1:8765` or `http://localhost:8765`; other host names are refused on purpose (DNS-rebinding guard) |
| `pytest` collects `vendor_refs/` and errors | Run from the repo root so `pytest.ini` applies (`testpaths = tests`) |
