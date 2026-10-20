# SETUP — exact steps, with evidence

Every command in this file comes from one of three places: the README or docs of a pinned upstream repo (commit hash given), the tool's own `--help` output, or our own scripts. If a step was not run yet, it says **NOT YET RUN**. If we could not confirm it, it says **VERIFY** or **BLOCKED**.

Pinned upstream sources (from `import/repos.lock.jsonl`, cloned 2026-10-07 IST):

| Repo | Commit | Licence (from LICENSE file) | Package version at that commit |
|---|---|---|---|
| exasol/mcp-server | `2dd3ab93f786a96aea967c6f5f66f9c1e68c850e` | MIT | `exasol-mcp-server` 2.2.0 (`pyproject.toml`) |
| exasol/pyexasol | `0d5adac9d6a9675128feeab1b8c93cd4e28582bc` | MIT | `pyexasol` 2.4.1 (`pyproject.toml`) |
| exasol-labs/exasol-agent-skills | `b355ba1d4ef2fa3cdf37ae323cff92a29b6ae618` | MIT | n/a (not read yet) |
| exasol-labs/exapump | `d32ff2b1045e9377c2aa38d5cb37733c17aea2a0` | MIT | n/a (not read yet) |
| exasol/transformers-extension | `90b17fcd3e9acd24cde3895328b06fc0cb492326` | MIT | n/a (not read yet) |

Re-create the clones with `bash import/clone_repos.sh` (writes `vendor_refs/`, which is git-ignored).

---

## 1. Exasol Personal instance

**DONE 2026-10-11** (local preset, Windows 11 amd64). Steps actually run, in order. Every command is from the launcher's own `--help` or `user-docs/content/{local-deployment,cli-reference}.md` in exasol/exasol-personal:

1. Prerequisites per `local-deployment.md`: "On Windows, the database runs through Podman's default machine. Windows Package Manager (`winget`) and the prerequisites for a Podman machine are required." Podman 5.8.3 was installed via winget (2026-10-08). WSL2 was already present.
2. Launcher: official release asset `exasol-personal_Windows_x86_64.zip` from https://github.com/exasol/exasol-personal/releases/tag/v2.3.0. SHA-256 `6300c83528d2f6a7a79a468351564bc75e88004f07b5cf28429be80ff94e6fcf` matches the release's `exasol-personal_2.3.0_checksums.txt`. `exasol.exe version` → `2.3.0`.
3. `exasol install local --auto-approve`. `--auto-approve` is required for the Podman-machine host change when no terminal can prompt (local-deployment.md "Windows host preparation"). It created Podman's default machine from `quay.io/podman/machine-os:5.8` and started the database. (The first attempt, on 2026-10-08, failed at `podman machine init` with "lookup quay.io: no such host", a transient DNS error. Rerunning `install` resumes, per its `--help`.)
4. `exasol info` → Deployment State `running`, Server `127.0.0.1`, Port `8563`, UserId `sys`, certificate validation "disable validation / use nocertcheck". The initial password is `exasol` (local-deployment.md: "The initial local database credentials are `sys` / `exasol`").
5. **Python UDFs need a script language container.** cli-reference.md: "Local deployments ship without any SLC installed". Without one, `CREATE ... PYTHON3 SCALAR SCRIPT` fails with "No usable script language container is installed". Fix: `exasol slc install PYTHON3`, which installs `python-3.12` / `11.2.0` and restarts the DB. Loaded data survives the restart.
6. `python verify/v0_connect.py` with `EXA_DSN=127.0.0.1/nocertcheck:8563` → server version `2026.2.0-nano.3`.

Platform question from 01 §1: resolved by [EVT-LOCAL-OK]. Local installs are part of the official starter kit, and this is the official launcher's local preset, not `exasol/docker-db`.

Useful launcher commands: `exasol stop`, `exasol start`, `exasol info`, `exasol slc list`.

## 2. Credentials (env vars only, never committed)

Our scripts and the MCP server read the same three variables. The names come from the MCP server's `doc/user_guide/db_connection_setup.rst` ("On-Prem Backend" table) @ `2dd3ab9`:

| Variable | Required (per MCP docs) |
|---|---|
| `EXA_DSN` (e.g. `demodb.exasol.com:8563`) | yes |
| `EXA_USER` | yes |
| `EXA_PASSWORD` | one of EXA_PASSWORD / EXA_ACCESS_TOKEN / EXA_REFRESH_TOKEN |

PowerShell (current session only):
```powershell
$env:EXA_DSN = "<host>:<port>"
$env:EXA_USER = "<user>"
$env:EXA_PASSWORD = "<password>"
```
For the local deployment in §1 the DSN is `127.0.0.1/nocertcheck:8563`. pyexasol 2.4.1 takes the TLS fingerprint (or `nocertcheck`) inside the DSN as `hostname[/fingerprint][:port]` (pyexasol `doc/changes/changes_2.4.1.md`, `changes_1.1.0.md`). Use `nocertcheck` only for this local, self-signed instance.
Set `TATGUARD_HOST_LABEL` (e.g. `exasol-personal-2.3.0-local-windows-podman`) so `reports/timings.csv` records which instance produced each timing.
`.env` files are git-ignored. Don't put credentials in any tracked file.

## 3. pyexasol

Source: `pyexasol/doc/user_guide/getting_started.rst` @ `0d5adac`:

> PyExasol is distributed through PyPI … It can be installed via pip …
> `pip install pyexasol`

Prerequisites quoted from the same file: "Exasol >= 8", "Python >= 3.10". (The README at the same commit says "Exasol >= 7.1". The two disagree, so we treat Exasol >= 8 as the binding requirement.)

What we will run (pinned to the version at the cloned commit; this is our choice):
```bash
pip install "pyexasol==2.4.1" pyyaml
```
**DONE** in a venv at `.venv/` (git-ignored). Installed and verified: pyexasol 2.4.1, PyYAML 6.0.3, numpy 2.5.3, pandas 3.0.6, pyarrow 25.0.1, pytest 9.1.1.

Optional extras listed in getting_started.rst: `pandas`, `polars`, `pyarrow`, `orjson`, `rapidjson`, `ujson`, installed with `pip install pyexasol[<optional-package-name>]`. Phase 1 bulk load will probably need `pandas` or `pyarrow`; we will decide then.

Connection test: `python verify/v0_connect.py` (see `03_VERIFIER.md` V0).

## 4. Exasol MCP server (agent, Phase 4)

Source: `mcp-server/README.rst` and `doc/user_guide/{server_setup,db_connection_setup,tool_setup,tool_list}.rst` @ `2dd3ab9`.

Prerequisites (README): "Python >= 3.11" and an MCP client application. `pyproject.toml` says `requires-python = ">=3.11,<3.15"`. Local Python is 3.13.5.

Install options quoted from the README:
```shell
uv --version                               # uv must be installed (local: uv 0.11.3)
uv tool install exasol-mcp-server@latest   # optional install
exasol-mcp-server-http --host <server-host> --port <server-port>   # HTTP mode
```
MCP client config from the README (the standard `mcpServers` JSON client config):
```json
{
  "mcpServers": {
    "exasol_db": {
      "command": "uvx",
      "args": ["exasol-mcp-server@latest"],
      "env": { "EXA_DSN": "my-dsn", "EXA_USER": "my-user-name", "EXA_PASSWORD": "my-password" }
    }
  }
}
```
**Our deviation (DESIGN):** pin the version instead of `@latest`, so the demo can be reproduced. `uv tool run --help` (uv 0.11.3) shows `--from <FROM>  Use the given package to provide the command`, so the pinned form will be `uvx --from "exasol-mcp-server==2.2.0" exasol-mcp-server`. **Checked 2026-10-11:** `pip index versions exasol-mcp-server` lists 2.2.0, and `uvx --from "exasol-mcp-server==2.2.0" exasol-mcp-server` starts the server (FastMCP banner, stdio transport).

### Settings (`EXA_MCP_SETTINGS`: a JSON string, or a path to a JSON file)

Keys we will use. Every key and its default is quoted from tool_setup.rst §"Default server settings":

| Key | Default | TAT Guard value | Why |
|---|---|---|---|
| `enable_read_query` | `false` | `true` | agent must run SELECTs (`execute_exasol_query`) |
| `enable_write_query` | `false` | **`false`** | agent never writes directly (DESIGN: PROPOSED → human APPROVE) |
| `disable_elicitation` | `false` | `false` | never disable |
| `views.enable` | `false` | `true` | `RECON.PENALTY_EXPOSURE` is a view |
| `default_row_limit` | `null` | e.g. `1000` (DESIGN) | guard against unbounded results |
| `enable_query_profiling` | `false` | optional | "why is it slow" answers |
| `enable_read_bucketfs` / `enable_write_bucketfs` | `false` | `false` | not needed |
| `schemas.like_pattern` | `""` | restrict to our schemas (exact pattern TBD in Phase 4) | |

**As built:** the settings live in `agent/mcp_reader.py` (`MCP_SETTINGS`) and are passed through `EXA_MCP_SETTINGS`. On top of the draft below we also set `query_result_format: tabular` and `enable_preprocessor_tools: false` (the default `true` exposes `set_exasol_preprocessor`, which changes session state). Draft as planned:
```json
{
  "enable_read_query": true,
  "enable_write_query": false,
  "views": { "enable": true },
  "default_row_limit": 1000
}
```

Read-only tools exposed with these settings (from tool_list.rst): `execute_exasol_query` ("must be a SELECT statement … SELECT INTO command is not allowed"), the metadata `list_*`/`find_*`/`describe_*` tools, and the dialect tools.

**Resolved in Phase 4 (2026-10-11):** proposals go through `agent/actions.py` on the backend's admin connection, not through MCP. The MCP server logs in as `TATGUARD_AGENT`, a DB user with only CREATE SESSION and SELECT on RAW, RECON and AUDIT (created by `agent/setup_agent_user.py`), so writes are refused by the database as well as by the MCP server. `verify/v4_agent.py` tests both layers. Original note: with `enable_write_query=false`, the MCP server cannot INSERT into `AUDIT.PROPOSED_ACTIONS`. The "propose" step therefore has to be our own narrow tool in `agent/tools.py` (an insert-only, parameterised function), not MCP's generic write tool. The alternative, enabling `execute_exasol_write_query` with elicitation, would let the LLM write arbitrary DML after a single click, and 01 §Phase 4 forbids that.

Telemetry (server_setup.rst): set `EXASOL_TELEMETRY_DISABLE` (any value) to opt out.

TLS options (db_connection_setup.rst): `EXA_SSL_CERT_VALIDATION` (default true; "never [false] in production"), `EXA_SSL_TRUSTED_CA`, `EXA_SSL_CLIENT_CERT`. Whether Exasol Personal needs a custom CA is UNKNOWN until it is provisioned.

## 5. Local tooling observed (2026-10-07)

| Tool | Status |
|---|---|
| Python | 3.13.5 |
| git | 2.52.0 |
| uv | 0.11.3 |
| docker | not installed |
| gh (GitHub CLI) | not installed |
