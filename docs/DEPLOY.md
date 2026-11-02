# DEPLOY: run TAT Guard from scratch

This is the run guide. On macOS or Linux the short version is `bash scripts/run_demo.sh`, which does everything below.
The numbered steps were run on Windows 11 (amd64) on 2026-10-11. `scripts/run_demo.sh` was run on macOS on Apple Silicon with
launcher 2.2.0 on 2026-11-02, starting with Exasol installed; `exasol install local` itself was not re-run.
Why each step looks the way it does (with sources) is in [SETUP.md](SETUP.md).

> **Not yet done:** following this guide on a machine with nothing installed. Until someone does, treat any step that
> needed knowledge outside this file as a bug in this file.

## Run it for a jury

**Before going live**, on the machine that will serve the demo:

1. In **Terminal.app** on macOS: `exasol start`, or `bash scripts/run_demo.sh` for a fresh load.
2. Put `GEMINI_API_KEY=...` in `.env`. Without it, Ask offers three prepared questions and says so. **Enable billing on the key
   before a jury uses it**: the free tier allows only 20 requests a day per model, and one question takes 2 to 5. Do not spend
   the free quota rehearsing on the day.
3. `brew install cloudflared`, stop any running server, then `bash scripts/go_public.sh`. It prints the link to send, with the
   access code in it. A judge opens it in a browser and needs nothing else.
4. Keep the Mac on power. The script keeps it awake. Press Ctrl-C to take the link down.

The link changes each time a quick tunnel starts, so start it once. For a fixed address use a named Cloudflare tunnel on
your own domain, and set `TATGUARD_PUBLIC_HOST` to that host name.

**Between judges**: open `http://127.0.0.1:8765/#/proof` on the serving machine and press **Reset the demo** (about 20 seconds).
It also resets itself after 30 idle minutes. Everyone shares one bank, so a judge sees what the last one did until then.

**If something goes wrong**: stop the script, run `exasol status`, then start again. The data is safe in Exasol.

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

**macOS / Linux** (official docs): `curl https://downloads.exasol.com/exasol-personal/installer.sh | sh`,
then `exasol install local` and `exasol slc install PYTHON3`. On macOS the database runs in a VM, which the app reaches over
macOS's Local Network permission. Run `exasol` from Terminal.app, or allow your editor in System Settings → Privacy & Security
→ Local Network, or `exasol start` ends as `interrupted`. Once it is up, any app can reach it on 127.0.0.1.

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
.\.venv\Scripts\python agent\setup_app_user.py                                     # the user the app runs as: owns its own schemas only
.\.venv\Scripts\python agent\setup_agent_user.py                                   # read-only DB user for the agent
.\.venv\Scripts\python generator\generate.py --rows 1000000 --seed 42 --out data\1m   # SYNTHETIC data, ~1 min
.\.venv\Scripts\python recon\pipeline.py load --data data\1m
.\.venv\Scripts\python verify\v1_load.py --data data\1m                            # loads ground truth, checks counts
.\.venv\Scripts\python recon\pipeline.py recon
```

## 5. Start the UI

```powershell
.\.venv\Scripts\python ui\server.py        # http://127.0.0.1:8765
```
The first start downloads the pinned `exasol-mcp-server==2.2.0` through uvx (a few seconds after that). **Assistant** →
*How it answers* shows deterministic playbooks unless `GEMINI_API_KEY` is set, in which case it shows Google Gemini.

The app opens on **Live**. A checklist at the top follows the demo path and fills in as each step is done.

Demo flow: **Live**: press Pay with "Money leaves, payee gets nothing" → the verdict names what happened → **Move the clock 2 days**
and watch the figures move → **Open this case** → as Asha, **Propose reversal** → switch to Vikram at the top right → **Approve**
→ the reconciliation re-runs and the case closes → **Ask**: "Why did breaks spike?" → **Deliver the late file** on Live and watch
the breaks clear → **Proof**: live accuracy and the audit log. **Export** on Cases downloads the current view.

The import API (`/api/connect`, `/api/upload`, `/api/import`) has no page, and is served to a local install only, never over a public link.

The late file also "arrives" with `.\.venv\Scripts\python recon\pipeline.py ingest-pending --data data\1m`.
To reset the demo from a terminal, repeat the commands in step 4 from `pipeline.py load`, adding `--reset-audit` to the load.

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
| UI returns `403 request not from the TAT Guard page` | Open the UI as `http://127.0.0.1:8765` or `http://localhost:8765`; other host names are refused on purpose (DNS-rebinding guard). For a public name, set `TATGUARD_PUBLIC_HOST` |
| `exasol start` ends `interrupted`, `no route to host`, on macOS | The app that ran it lacks the Local Network permission. Run `exasol stop; exasol start` from Terminal.app. The `stop` matters: the old VM's forwarder stays blocked until it is replaced |
| Ask says no AI model is configured | Add `GEMINI_API_KEY` to `.env` and restart the server |
| Ask says the model has used up its quota | The free tier's daily limit ran out. Enable billing on the key, or wait for it to reset |
| `pytest` collects `vendor_refs/` and errors | Run from the repo root so `pytest.ini` applies (`testpaths = tests`) |
