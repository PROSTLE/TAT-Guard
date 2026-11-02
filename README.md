<div align="center">

<img src="docs/img/logo.svg" alt="TAT Guard logo: a shield with a clock, holding a rupee coin" width="210">

# TAT Guard

**Every stuck rupee, on a clock.**

Make a UPI payment fail and watch Exasol catch it. A reconciliation workbench that finds the customers a bank owes,
puts the most urgent first, and proves what was done.

<sub>Built on</sub><br>
<a href="https://www.exasol.com/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/exasol/exasol-personal/f5e4c012c93755705675300844c7dcd285b2a261/static/Exasol_Logo_2025_Bright.svg">
    <img src="https://raw.githubusercontent.com/exasol/exasol-personal/f5e4c012c93755705675300844c7dcd285b2a261/static/Exasol_Logo_2025_Dark.svg" alt="Exasol" width="150">
  </picture>
</a>

**[Demo video](deliverables/demo_video.mp4)** · **[Presentation (PDF)](deliverables/TAT_Guard.pdf)** · **[Demo video on Google Drive](https://drive.google.com/file/d/1QNgFqSpvGM3b4qivJFTD0B0iJ-7oxpyW/view?usp=sharing)** · **[Presentation on Google Drive](https://drive.google.com/file/d/10Bs54uf-PvdVeF3sUjZnVdW4eiQpfGBw/view?usp=sharing)**

[Try it](#try-it) · [Why it exists](#why-it-exists) · [Who it is for](#who-it-is-for) · [How it works](#how-it-works) · [Quick start](#quick-start) · [Results](#results) · [Safety](#safety-model) · [Limitations](#limitations-and-open-items)

</div>

## Demo video and presentation

| What | Link |
|---|---|
| Demo video | [deliverables/demo_video.mp4](deliverables/demo_video.mp4) |
| Presentation (PPT as PDF) | [deliverables/TAT_Guard.pdf](deliverables/TAT_Guard.pdf) |
| Demo video on Google Drive | [Open on Google Drive](https://drive.google.com/file/d/1QNgFqSpvGM3b4qivJFTD0B0iJ-7oxpyW/view?usp=sharing) |
| Presentation on Google Drive | [Open on Google Drive](https://drive.google.com/file/d/10Bs54uf-PvdVeF3sUjZnVdW4eiQpfGBw/view?usp=sharing) |

## Try it

Open the link from the team, or run it yourself with `bash scripts/run_demo.sh`. On Home, press **Try it live**. Then:

1. **Make a payment fail.** Pick what goes wrong. Your payment becomes real rows in the three source tables.
2. **Watch Exasol catch it.** The same reconciliation that handles every other payment runs across all of them, pass by pass.
   The verdict is compared with what you injected, and the reconciliation is never told.
3. **Move the clock.** Every penalty is a live view, so the rupee figures move as soon as the date does.
4. **Fix it as two people.** Asha proposes the reversal. Only Vikram can approve it, and the posting really goes to the ledger table.
5. **Ask the data anything.** The AI analyst writes SQL, runs it read-only on Exasol, and shows every query.
6. **Check the proof.** Accuracy is computed live, including the payments you just made.

The **Exasol, live** panel on that page shows every statement as it happens: the exact SQL, its real time and row count, and
for each pass the execution plan from Exasol's own profile. The rest of the app works as before, on the same data.

### What is real and what is not

| Real | Synthetic |
|---|---|
| The Exasol database, every statement on the page, every timing and row count | The payment records. The event allows public or synthetic data only [EVT-DATA], and real bank records could not be used anywhere |
| The matching, classification and penalty logic, run in full on every action | The file layouts, which are stand-ins, because the real NPCI, switch and CBS formats are not public |
| The TAT rules, from the RBI circular [RBI-TAT-REF] | Bank codes, names and accounts. Nothing here is a statement about any real bank |
| The approval flow, audit log and ledger rows it writes | The posting itself: it writes a row to our ledger table, and no money moves |


## Why it exists

A customer sends money over UPI. The app says the payment failed, but the balance has already gone down. The customer
waits, and very often nobody at the bank knows yet that this particular payment is stuck.

The reason is not carelessness. The evidence sits in three separate systems: the bank's UPI switch, the NPCI settlement
file and the core-banking ledger. Someone has to line them up, transaction by transaction, while a regulatory clock is
already running.

> **Bank reconciliation teams** can't see which failed UPI debits are about to start costing money, **because**
> the evidence is split across three systems that must be matched transaction by transaction. Meanwhile the
> compensation clock keeps running. **If this worked,** they would see every stuck rupee on a clock, stop the cases that
> add cost tomorrow first, and show that compensation was paid without the customer having to complain.
> (Template from the event page [EVT-PROBLEM-FORMAT].)

**The rule behind the clock**

- If a UPI fund transfer leaves the customer debited but the beneficiary is not credited, the reversal is
  due by T+1 [RBI-TAT-UPI-P2P]. For a UPI merchant payment it is due by T+5 [RBI-TAT-UPI-P2M].
- Beyond that the customer is owed ₹100 per day [RBI-TAT-COMP], paid suo moto, without a complaint [RBI-TAT-SUOMOTO].
- T is the calendar date of the transaction [RBI-TAT-DAYCOUNT]. Source: RBI circular [RBI-TAT-REF].

**Why the scale matters**

- UPI handled 24.07 bn transactions in Sept 2026, about 802 million a day [UPI-SEP26] (secondary source).
- **Impact (illustrative, not measured):** if 0.01% of daily UPI transactions ended debited-not-credited and 5% [ASSUMPTION]
  of those missed TAT by one day, compensation would be about ₹4.0 lakh a day, or ₹14.6 crore a year [ASSUMPTION]. Both rates
  are our assumptions, not data. Recompute with `python crosscheck/recompute_numbers.py`.

## Who it is for

TAT Guard is made for the operations and reconciliation teams of banks that process UPI payments, and for the people
who have to answer for their work. It is a working prototype on synthetic data and has not been deployed at a bank.

| If you are a... | You need to know... | TAT Guard gives you... |
|---|---|---|
| **Reconciliation analyst** | Which case to pick up next, and why | A ranked Work Queue, and one case view showing what each system recorded |
| **Operations lead** | What will cost money tomorrow, and where the work is stuck | The Today page, a chase list by payee bank, and a view of open cases by age |
| **Approver (checker)** | Exactly what will change before saying yes | Approvals, showing the amount to be posted; nobody can approve their own proposal |
| **Compliance or internal audit** | Whether compensation was really paid, unprompted | A compensation register to export, and an audit log with the SQL and the before and after figures |
| **Data or technology team** | Whether this can be trusted and run on their own database | Open SQL, a verifier against ground truth, and reconciliation that runs inside Exasol |

## How it works

### The journey of the data

Three sources go in. A ranked list of work comes out. Every step between them runs as SQL inside Exasol, and every
screen reads the live result.

```mermaid
flowchart TB
    subgraph IN["Three sources"]
        direction LR
        A["UPI switch log"] ~~~ B["NPCI settlement file"] ~~~ C["Core-banking ledger"]
    end
    subgraph EX["Inside Exasol"]
        direction LR
        D["RAW tables"] --> E["Four matching passes"] --> F["Classify each break"] --> G["TAT clock and rupee exposure"]
    end
    subgraph OUT["For people"]
        direction LR
        H["Ranked work queue"] --> I["Human approval"] --> J["Audit log"]
    end
    IN --> EX --> OUT
```

Each approved fix goes back through Exasol: the reconciliation runs again, so the queue always reflects what was done.

**Where the data comes from.** No figure is stored in the page. `generator/generate.py` writes synthetic CSV files, those
load into Exasol, the reconciliation runs there, and every screen reads the result. The **Connect & Import** page does
this without a terminal: pick an Exasol database, then load the sample dataset, four CSV files, or four tables from a
schema. New files are checked in a staging schema first, so a bad file leaves the loaded data alone. On top of that base,
visitors add their own payments, an outage or the late file from the Live demo page, in the same tables, through `ui/live.py`.

### What happens at each step

1. **Synthetic data with ground truth.** `generator/generate.py` writes the three sources, a settlement-file arrival
   log and a ground-truth table. It injects six break types, including a late settlement file. The output is
   deterministic: the same seed gives byte-identical files.
2. **Reconciliation in Exasol.** There are four matching passes, each catching what the one before could not.

   ```mermaid
   flowchart TD
       A["Pass 1: transaction id join"] -->|"still unmatched"| B["Pass 2: RRN and time window"]
       B -->|"still unmatched"| C["Pass 3: Python UDF reads the reference<br/>out of messy ledger narrations"]
       C -->|"still unmatched"| D["Pass 4: fuzzy scoring for debits<br/>with no reference at all"]
       D --> E["RECON.EXCEPTIONS: every break, classified"]
   ```

   The Python UDF is `RECON.EXTRACT_REF`.
3. **TAT clock and ₹ exposure.** `RECON.PENALTY_EXPOSURE` computes the deadline, the penalty so far, the amount owed
   tomorrow and the suo-moto compensation status (PAID / UNDERPAID / MISSING). TAT days and ₹/day are loaded from
   `facts.yaml`, never typed into SQL. A partial reversal does not stop the clock. Compensation is a flat rate per day, so
   what has accrued is a sunk cost and every accruing case costs the same to leave open. The queue therefore ranks what
   a case **adds tomorrow** first, then the longest wait, not the biggest running total.
4. **An analyst that can only read.** With `GEMINI_API_KEY` set, Google Gemini writes its own SQL for any question, runs it
   through the Exasol MCP server as a read-only user, corrects its own failed queries, and remembers the conversation. Every
   number in an answer must appear in that turn's query results; a grounding guard enforces this. Without a key, three
   prepared questions still work, and the page says that is what they are. If the model fails, the answer says so.
5. **Actions that need a person.** The analyst can only create `PROPOSED` rows. The server knows who is signed in: an analyst
   proposes and an approver decides, and neither can do the other's job. The backend runs a fixed SQL template, re-runs the
   reconciliation and writes `AUDIT.ACTION_LOG` with the SQL and before/after values.

### The life of a case

A debit-no-credit case moves through these states. The labels are the ones used on the Work Queue.

```mermaid
stateDiagram-v2
    direction TB
    [*] --> WithinTAT: customer debited, not credited
    WithinTAT --> DueToday: deadline is near
    DueToday --> Overdue: deadline passes
    WithinTAT --> Closed: reversed in time
    DueToday --> Closed: reversed in time
    Overdue --> CompensationDue: reversed late
    CompensationDue --> Closed: compensation paid
    Closed --> [*]
    WithinTAT: Within TAT
    DueToday: Due today
    Overdue: Overdue (adds cost daily)
    CompensationDue: Compensation due
    Closed: Off the queue
```

### From a question to an approved fix

The assistant can look and suggest. It cannot change anything, and the proposer cannot approve their own proposal.

```mermaid
sequenceDiagram
    actor A as Analyst
    participant G as Assistant
    participant M as Exasol MCP server<br/>(read-only user)
    participant B as TAT Guard backend
    participant E as Exasol
    actor C as Named approver
    A->>G: Why did breaks spike?
    G->>M: SELECT queries
    M->>E: Read
    E-->>G: Results
    G-->>A: Answer, with every query shown
    G->>B: Propose a fix
    B-->>C: Waits in Approvals
    C->>B: Approve
    B->>E: Fixed SQL, then re-run
    B->>E: Write the audit log
```

### What runs where

```mermaid
flowchart TB
    U["Browser"] --> S["ui/server.py on 127.0.0.1"]
    S -->|"page reads"| R["Read-only DB user<br/>SELECT on RAW, RECON, AUDIT"]
    S -->|"/api/ask"| AG["agent/agent.py and grounding guard"]
    AG --> MC["exasol-mcp-server, read queries only"]
    MC --> R
    S -->|"payments, approvals, recon"| W["App user: owns these schemas only<br/>ui/live.py, agent/actions.py, recon/pipeline.py"]
    R --> X[("Exasol: RAW, RECON, AUDIT")]
    W --> X
    V["verify/ scripts"] --> GT[("VERIFIER.GROUND_TRUTH")]
    F["facts.yaml"] -->|"TAT rules"| X
```

The agent's database user has no access to `VERIFIER`, so it can never see the answer key. The app's database user owns
RAW, RECON, AUDIT and VERIFIER and nothing else, so it can run on an instance shared with other work. One worker thread
owns every write, so visitors cannot collide. `tests/test_ui_contract.py` fails if page and server drift apart.

## See it

**Live demo** is where a visitor tries it: the payment, what each system recorded, the reconciliation and the verdict.

![The Live demo page: a failed payment, the reconciliation pass by pass, the Exasol activity and the verdict](docs/img/live.png)

Home explains the problem and offers a guided demo through the real pages.

![TAT Guard home: the problem, how it works and where to start](docs/img/home.png)

**Today** opens with what needs doing, built from live counts. **Insights** then shows one topic at a time: open cases
by age, a chase list by payee bank, and a compensation register that exports every case past TAT as evidence that
compensation was paid without a complaint.

![TAT Guard Today page: what needs doing, the cost added tomorrow, and the cases to fix first](docs/img/dashboard.png)

**Connect & Import** shows where the data comes from, with the real load and reconciliation timings.

![Connect and import: where the data comes from, with the real load and reconciliation timings](docs/img/connect.png)

| Work queue | One case |
|---|---|
| ![Work queue on the view of cases adding cost tomorrow](docs/img/work-queue.png) | ![A case with its next step, TAT clock and what each system recorded](docs/img/case.png) |

## Quick start

From a clean clone, on macOS or Linux:

```
bash scripts/run_demo.sh
```

It installs what is missing, loads the synthetic data, runs the reconciliation and starts the app at http://127.0.0.1:8765.
It needs Exasol Personal, uv and Python 3.12 or later, and stops with the fix if one is missing. On macOS, run it from
Terminal.app. Add `GEMINI_API_KEY` to `.env` to switch on the AI analyst.

To put it on a public link behind an access code, run `bash scripts/go_public.sh`. Details, Windows steps and
troubleshooting are in [docs/DEPLOY.md](docs/DEPLOY.md).

Pages: Home, Live demo, Connect & Import, Today, Work Queue, Approvals, Insights, Transactions, Assistant, Audit Log, Reports, Data Sources. Every figure is a live query.

## Results

Measured on this repo's own runs; the reports are in `reports/`.

| Check | Result | Evidence |
|---|---|---|
| Matching accuracy vs ground truth at 1M rows | precision 1.0 and recall 1.0 for all five break classes; re-run after the 31 Oct SQL changes [MEASURED] | `reports/verifier_V2_1000000_*.md` |
| Exasol vs an independent pandas matcher | 46,618 vs 46,618 exceptions, 0 disagreements; re-run on 31 Oct [MEASURED] | `python crosscheck/dual_impl.py --csv data/1m --exasol` |
| Penalty SQL view vs `recon/penalty.py` | 966 cases, 0 differences; re-run on 31 Oct [MEASURED] | `python crosscheck/penalty_check.py` |
| Late settlement file scenario | root cause named correctly by the agent; ingesting the file clears 44,807 breaks [MEASURED] | V2 and V4 reports |
| Agent safety (V4) | 8 pass, 1 blocked: the full gate has not finished on the real model, see Limitations [MEASURED] | `reports/verifier_V4_*.md` |
| Prompt injection, real model | an instruction planted in a ledger note was read and refused; audit tables unchanged [MEASURED] | run on 2 Nov with `gemini-flash-lite-latest`, not a fallback |
| Questions it should refuse, real model | a question it cannot answer, the answer key, and a request to delete data and approve everything were all refused; nothing changed [MEASURED] | run on 2 Nov through the page |
| Edge cases the generator never makes (partial and instalment reversals, double debit on a failed payment, ranking) | 14 of 14 pass, through the real SQL on Exasol in throwaway schemas [MEASURED] | `reports/verifier_V5_*.md` |
| Matching accuracy at 10M rows | overall precision 469,007 / 469,024; `NPCI_SUCCESS_NO_CBS` precision 0.9965, recall 0.9990; every other class 1.0 [MEASURED] | `reports/verifier_V2_10000000_*.md` |
| Penalty SQL view vs `recon/penalty.py` at 10M | 9,409 cases, 0 differences [MEASURED] | `python crosscheck/penalty_check.py` |
| Recon run time, 1M transactions | 16.9 s to 37.9 s for all seven SQL steps across four runs on 11-12 Oct; the slower two ran while other heavy jobs used the laptop. 39.2 s to 40.8 s across three runs on 31 Oct, after the SQL changes; we have not isolated why these are slower [MEASURED] | `reports/timings.csv` |
| Same 1M reconciliation, pandas vs Exasol | pandas 1,020.4 s to read the CSVs, match and classify; Exasol 40.5 s for the recon, plus 16.8 s to bulk load the same CSVs. Same laptop, one run of each, same exceptions. The pandas matcher is an untuned cross-check, so this is not a best-possible pandas time [MEASURED] | `reports/benchmark_1000000_*.md` |
| Recon run time, 10M transactions | 274 s cold, 284 s warm [MEASURED] | `reports/timings.csv`, scale `10000000` |
| Bulk load, 10M transactions | about 16 min for the three source files (CBS ledger alone 12.5 min) [MEASURED] | `reports/timings.csv` |
| Live payments through the page | 1,00,002 of 1,00,002 classified correctly across all eight scenarios and a 50,000 payment outage, 0 false alarms, 0 missed [MEASURED] | Live demo page, 2 Nov; the check runs live |
| Recon run time, 1M transactions, MacBook Air M4 | 11.5 s to 13.3 s on Exasol Personal's macOS VM with 2 CPUs and 8 GB [MEASURED] | `reports/timings.csv`, host `exasol-personal-2.2.0-local-macos-arm64` |
| Moving the clock | every open case repriced in 11 ms to 12 ms, because penalties are a view [MEASURED] | shown on the page each time |

**Where the 10M errors come from.** 5,736 debits [MEASURED] carry no reference at all in their narration (our injected
`NARRATION_NOREF` break). The fuzzy pass auto-matched 5,729 [MEASURED] of them. 7 were too ambiguous (round amounts at the
busiest bank inside the time window), so they went to a human as `UNMATCHED_CBS_DEBIT`. 3 were matched to the wrong
transaction, which hid 3 real `NPCI_SUCCESS_NO_CBS` breaks [MEASURED]. Our synthetic NPCI and switch records carry no payee field, so there
is no further signal to separate these cases. We report the errors rather than tune the generator or matcher to remove them.

**About the timings.** All runs were on one Windows laptop (12 CPUs, about 2 GB of RAM free during the runs)
with Exasol Personal's local preset in Podman on WSL2, not on server hardware. 10× the rows took about 15× the recon
time here, which points to memory pressure on this machine; we have not measured the cloud preset. The 50M scale in
the plan was **not run**: at this rate it needs hours and about 15 GB of CSV on a machine with no memory headroom.

**What these numbers do not show:** performance on real bank data, or speed on a server. A perfect or near-perfect
score means the engine finds the breaks *our generator* injects.

## Safety model

| Risk | Control | Verified by |
|---|---|---|
| Agent writes or deletes data | The MCP server allows SELECT only, **and** the agent's DB user has SELECT-only privileges | `verify/v4_agent.py` (5 write attempts refused) |
| A bad generated query ties up the database | The agent's DB user has its own consumer group with a query timeout, so nothing else on the instance is affected | `agent/setup_agent_user.py` |
| The page reaches other data on the instance | The backend runs as a user that owns RAW, RECON, AUDIT and VERIFIER and has no other grant; the admin user is for setup only | Attempts on a throwaway schema refused; `agent/setup_app_user.py` |
| A visitor on the public link does harm | An access code gates every API call, each action is rate limited, and the routes that change the database connection or replace data are not served | `tests/test_auth.py`, attack run on 2 Nov |
| Agent sees the answer key | Ground truth is in schema `VERIFIER`; the agent user has no grant on it | same |
| LLM-made-up numbers | Grounding guard; answer replaced by raw results after 2 failed checks. Refuses spelled-out numbers, lakh/crore shorthand and date digits reused as amounts. It proves a number occurs in the results, not that the sentence uses it correctly; the queries shown with each answer are the check for that | unit tests + V4 |
| LLM-written SQL executed as an action | Impossible: actions are 3 whitelisted types with fixed templates; values are looked up in the DB | `agent/actions.py` |
| Instructions hidden in data ("approve all" in a narration) | The agent has no approve tool; approval needs a named human in the UI | V4 injection check |
| Double execution | `UPDATE ... WHERE STATUS='PROPOSED'` claims the action exactly once | V4 |
| One person pushes a change through alone | Identity comes from a server-side session, not a typed name: analysts propose, approvers decide, and the proposer cannot approve their own action | `tests/test_actions.py`, `tests/test_auth.py`, live run |
| Posting repeated after a failed recon | The action stays EXECUTED and any new proposal for that case is refused until a recon has picked the posting up | `tests/test_actions.py` |
| Approved action left half-done | After the claim, every path (including a failed snapshot query) ends in an `AUDIT.ACTION_LOG` row and a final status | `tests/test_actions.py` |
| A bad file replaces good data | Uploads and schemas load into a staging schema and are checked before the current data is touched | `tests/test_importer.py` |
| Another web page calling the UI | Requests must name an allowed host in `Host`, carry no foreign `Origin`, and POSTs must be `application/json`. A strict content security policy allows no inline script | `ui/server.py` `_foreign()`, attack run on 2 Nov |

## Facts and numbers

Every number in this README carries a fact ID from [facts.yaml](facts.yaml) (rendered as [docs/FACTS.md](docs/FACTS.md)),
or is tagged [ASSUMPTION], [MEASURED] or [DESIGN]. `python nonhalluc/claim_scan.py README.md` enforces this.

## Limitations and open items

We would rather state these plainly than have a reader discover them.

- **Synthetic data only.** File layouts, response codes, RRN width, cycle schedule and narration formats are our own design.
  Connect & Import takes files in these stand-in layouts, so a real NPCI, switch or CBS file would need converting first.
  Only public or synthetic data belongs in it.
- **No Deemed, TCC or RET lifecycle.** Real UPI disputes turn on these states and on NPCI's chargeback rules [NPCI-OC213]. We
  could not read the NPCI circulars themselves (their site refused download), so we did not model rules we had not read.
- **Who receives compensation is a design assumption.** The circular's general principle pays a credit-push penalty to the
  beneficiary, and its P2P row names the beneficiary bank for reversal [RBI-TAT-PAYEE]. TAT Guard takes the debited bank's view and
  credits the debited account. A bank would confirm this with compliance. The payee-bank chase list shows who holds each case.
- **The 10M results predate the 31 Oct SQL changes.** Those changes affect partial reversals, double debits on failed payments
  and queue rank, none of which change a class on generated data. The 1M checks were re-run; 10M was not.
- **The AI analyst depends on Gemini's quota.** It has been run live with the real model, but on the free tier that allows
  20 requests a day per model [MEASURED], and one question takes 2 to 5 requests. A long list of models stretches that to a few
  dozen questions a day; a jury needs billing enabled on the key. When every model is out, the page says so and falls
  back to prepared questions. The full V4 gate has not yet completed against the model in one run, because the daily
  limit ran out partway: the scripted questions fell back, and the gate now reports that as BLOCKED, not as a pass.
- **Connect & Import has untested paths.** Switching to a second Exasol database and the 10M sample import through the page
  have not been run. An import also empties the ground truth, so run `verify/v1_load.py` again before any `verify/` script.
  The page is not offered over a public link.
- **The sign-in is a demo's.** One access code, two fictional people, sessions held in memory. A bank would use its own
  identity provider. The roles and the rules around them are enforced on the server.
- **Visitors share one bank.** There is one ledger and one clock, as at a real bank, so a visitor sees what others did. The
  demo resets itself after 30 idle minutes [DESIGN].
- **The public link runs from one machine.** It lasts while that machine is on and the tunnel is up, and Exasol Personal's
  licence describes single-user use, so check with the organisers before relying on it for many people at once.
- **Executing an action simulates the bank's CBS posting** (one credit row) and re-runs the full reconciliation.
- **Local certificate check is off** (`nocertcheck`) for the self-signed local instance only.
- Whether the RBI circular has been superseded [RBI-TAT-STILL-IN-FORCE]: still VERIFY. We found no withdrawal, and RBI enforced
  it in 2025, but we have not read the annexes of RBI's Nov 2025 repeal. We say "no withdrawal found", not "confirmed in force".
- Exasol's native AI SQL functions [EXA-261-AI] are not used; extraction is a deterministic Python UDF.
- The run guide has been followed on a second machine (macOS, Apple Silicon, with Exasol already installed) but not on a machine with nothing installed.

## Credits and licence

TAT Guard runs on [Exasol Personal](https://github.com/exasol/exasol-personal) and reads through the official
[Exasol MCP server](https://github.com/exasol/mcp-server). Icons in the app are from [Lucide](https://lucide.dev/).

The Exasol name and logo belong to Exasol AG and appear here only to show the platform this project runs on. TAT Guard is
an independent project and is not affiliated with or endorsed by Exasol AG, NPCI or the Reserve Bank of India.

The code is released under the MIT licence. See [LICENSE](LICENSE).
