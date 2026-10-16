"""TAT Guard synthetic data generator (SYNTHETIC DATA ONLY).

Writes the three reconciliation sources, a settlement-file arrival log, a "pending" NPCI file that
arrives after the recon cut-off, and a ground-truth table of every injected break.

    python generator/generate.py --rows 1000000 --seed 42 --out data/1m

Real NPCI settlement, UPI switch and CBS ledger layouts are not public. Every layout, code and
narration here is a synthetic stand-in (see generator/config.yaml). Regulatory constants (TAT days,
Rs/day) come from facts.yaml via recon/rules.py, not from this file.

Determinism: each chunk has its own RNG seeded with (seed, chunk_index), and chunk_rows is fixed in
the config, so the same (seed, rows, days, config) gives byte-identical files.
"""
from __future__ import annotations

import argparse

import hashlib
import json
import pathlib
import re
import sys

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recon import rules  # noqa: E402

U64 = np.uint64
HEX = np.frombuffer(b"0123456789ABCDEF", dtype=np.uint8)
DIG = np.frombuffer(b"0123456789", dtype=np.uint8)
MAX_ROWS = 1 << 28            # keeps the RRN bijection below inside uint64 (see _rrn)
RRN_MULT = 61_234_567_891     # odd, not divisible by 5 -> bijection mod 10^12; < 2^36
ID_MULT = 0x9E3779B97F4A7C15  # odd -> bijection mod 2^64

# outcome codes (index into OUTCOMES)
OUTCOMES = ["SUCCESS", "BUSINESS_DECLINE", "DEBIT_NO_CREDIT", "NPCI_SUCCESS_NO_CBS", "AMOUNT_MISMATCH",
            "DUPLICATE_POSTING", "NARRATION_ONLY", "NARRATION_NOREF", "SWITCH_ID_MISSING"]
O = {name: i for i, name in enumerate(OUTCOMES)}
# exception class the matcher is expected to raise (None = should reconcile cleanly)
EXPECTED_CLASS = {"DEBIT_NO_CREDIT": "DEBIT_NO_CREDIT", "NPCI_SUCCESS_NO_CBS": "NPCI_SUCCESS_NO_CBS",
                  "AMOUNT_MISMATCH": "AMOUNT_MISMATCH", "DUPLICATE_POSTING": "DUPLICATE_POSTING",
                  "LATE_FILE": "LATE_FILE"}

SCHEMAS = {
    "npci_settlement": ["UPI_TXN_ID", "RRN", "TXN_TS", "SETTLEMENT_DT", "CYCLE_NO", "AMOUNT_PAISE",
                        "PAYER_BANK", "PAYEE_BANK", "TXN_TYPE", "RESP_CODE", "STATUS"],
    "npci_settlement_pending": None,  # same columns as npci_settlement
    "switch_log": ["UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "STATUS", "RESP_CODE", "CHANNEL"],
    "cbs_ledger": ["CBS_ENTRY_ID", "ACCOUNT_NO_MASKED", "POST_TS", "DR_CR", "AMOUNT_PAISE", "NARRATION"],
    "ground_truth": ["UPI_TXN_ID", "INJECTED_BREAK", "EXPECTED_CLASS", "TXN_TYPE", "TXN_DT",
                     "AMOUNT_PAISE", "REVERSAL_DT", "COMP_PAID_PAISE"],
}
SCHEMAS["npci_settlement_pending"] = SCHEMAS["npci_settlement"]


# ---------------------------------------------------------------- vectorised string helpers
def fixed_hex(x: np.ndarray, width: int) -> np.ndarray:
    shifts = (np.arange(width - 1, -1, -1, dtype=U64) * U64(4))
    nib = ((x.astype(U64)[:, None] >> shifts) & U64(0xF)).astype(np.intp)
    return np.ascontiguousarray(HEX[nib]).view(f"S{width}").ravel()


def fixed_dec(x: np.ndarray, width: int) -> np.ndarray:
    pows = U64(10) ** np.arange(width - 1, -1, -1, dtype=U64)
    d = ((x.astype(U64)[:, None] // pows) % U64(10)).astype(np.intp)
    return np.ascontiguousarray(DIG[d]).view(f"S{width}").ravel()


def cat(*parts) -> np.ndarray:
    """Concatenate byte-string arrays/scalars element-wise."""
    out = None
    for p in parts:
        p = np.asarray(p if not isinstance(p, str) else p.encode())
        out = p if out is None else np.strings.add(out, p)
    return out


_FIELD = re.compile(r"\{(\w+)\}")


def render(template: str, fields: dict[str, np.ndarray], n: int) -> np.ndarray:
    """Fill a '{field}' template for n rows, vectorised."""
    parts, pos = [], 0
    for m in _FIELD.finditer(template):
        if m.start() > pos:
            parts.append(template[pos:m.start()])
        parts.append(fields[m.group(1)])
        pos = m.end()
    if pos < len(template):
        parts.append(template[pos:])
    out = cat(*parts) if parts else np.array([b""])
    return np.broadcast_to(out, (n,)) if out.shape != (n,) else out


def render_choice(rng, templates: list[str], fields: dict[str, np.ndarray], n: int) -> np.ndarray:
    pick = rng.integers(0, len(templates), n)
    out = np.empty(n, dtype=object)
    for k, t in enumerate(templates):
        m = pick == k
        if m.any():
            out[m] = render(t, {f: v[m] for f, v in fields.items()}, int(m.sum()))
    return out


# ---------------------------------------------------------------- deterministic identifiers
def _txn_ids(idx: np.ndarray, prefix: str, key: int) -> np.ndarray:
    return cat(prefix, fixed_hex((idx.astype(U64) * U64(ID_MULT)) ^ U64(key), 16))


def _rrn(idx: np.ndarray, width: int, offset: int) -> np.ndarray:
    mod = U64(10 ** width)
    return fixed_dec((idx.astype(U64) * U64(RRN_MULT) + U64(offset)) % mod, width)


def _entry_ids(idx: np.ndarray, kind: int, key: int) -> np.ndarray:
    return cat("C", fixed_hex(((idx.astype(U64) * U64(8) + U64(kind)) * U64(ID_MULT)) ^ U64(key), 16))


# ---------------------------------------------------------------- arrow / csv
def ts_str(ts: np.ndarray) -> pa.Array:
    return pc.strftime(pa.array(ts.astype("datetime64[s]")), format="%Y-%m-%d %H:%M:%S")


def date_str(d: np.ndarray) -> pa.Array:
    return pc.strftime(pa.array(d.astype("datetime64[s]")), format="%Y-%m-%d")


def s(a) -> pa.Array:
    if isinstance(a, pa.Array):
        return a
    a = np.asarray(a)
    if a.dtype == object:
        return pa.array([None if v is None else v.decode() for v in a], type=pa.string())
    return pa.array(a).cast(pa.string())


class Writers:
    def __init__(self, out: pathlib.Path):
        self.out, self.w, self.rows = out, {}, {k: 0 for k in SCHEMAS}

    def write(self, name: str, cols: dict):
        names = SCHEMAS[name]
        tbl = pa.table({c: cols[c] for c in names})
        if name not in self.w:
            self.w[name] = pacsv.CSVWriter(str(self.out / f"{name}.csv"), tbl.schema,
                                           write_options=pacsv.WriteOptions(include_header=True))
        self.w[name].write_table(tbl)
        self.rows[name] += tbl.num_rows

    def close(self):
        for name in SCHEMAS:              # always produce every file, even if empty
            if name not in self.w:
                schema = pa.schema([(c, pa.string()) for c in SCHEMAS[name]])
                pacsv.CSVWriter(str(self.out / f"{name}.csv"), schema).close()
        for w in self.w.values():
            w.close()


# ---------------------------------------------------------------- core
class Gen:
    def __init__(self, cfg: dict, rows: int, seed: int, days: int):
        if rows > MAX_ROWS:
            raise SystemExit(f"--rows must be <= {MAX_ROWS}")
        self.cfg, self.rows, self.seed, self.days = cfg, rows, seed, days
        self.tat = rules.tat_days()
        self.paise_per_day = rules.paise_per_day()
        cal = cfg["calendar"]
        self.start = np.datetime64(cal["start_date"], "s")
        self.start_day = np.datetime64(cal["start_date"], "D")
        self.as_of = self.start + np.timedelta64(days * 86400 + int(cal["as_of_extra_hours"] * 3600), "s")
        hw = np.asarray(cal["hour_weights"], float)
        self.hour_p = hw / hw.sum()
        st = cfg["settlement"]
        self.cycles = int(st["cycles_per_day"])
        self.cycle_secs = 86400 // self.cycles
        if 86400 % self.cycles:
            raise SystemExit("cycles_per_day must divide 86400")
        rng = np.random.default_rng([seed, 1 << 20])   # file-level randomness, separate stream
        # settlement file schedule: expected and actual arrival per (day, cycle)
        n_files = days * self.cycles
        close = self.start + (np.arange(n_files) + 1) * np.timedelta64(self.cycle_secs, "s")
        self.file_expected = close + np.timedelta64(int(st["expected_lag_minutes"] * 60), "s")
        jitter = rng.integers(0, int(st["arrival_jitter_minutes"] * 60) + 1, n_files)
        self.file_arrived = self.file_expected + jitter.astype("timedelta64[s]")
        for lf in st.get("late_files") or []:
            d = lf["day_index"] % days
            k = d * self.cycles + int(lf["cycle"])
            self.file_arrived[k] = self.file_expected[k] + np.timedelta64(int(lf["delay_minutes"] * 60), "s")
        self.file_arrived_by_as_of = self.file_arrived <= self.as_of
        self.file_counts = np.zeros(n_files, dtype=np.int64)
        self.id_key = int(rng.integers(0, 1 << 63))
        self.rrn_off = int(rng.integers(0, 10 ** int(cfg["ids"]["rrn_digits"])))
        self.entry_key = int(rng.integers(0, 1 << 63))
        nb = int(cfg["ids"]["counterparty_banks"])
        self.banks = np.array([f"BNK{i + 1:02d}".encode() for i in range(nb)])
        zipf = 1.0 / np.arange(1, nb + 1) ** float(cfg["ids"]["counterparty_zipf_a"])
        self.bank_p = zipf / zipf.sum()
        oc = cfg["outcomes"]
        p = np.array([0.0] + [float(oc[k]) for k in OUTCOMES[1:]])
        if p.sum() >= 1:
            raise SystemExit("outcome probabilities must sum to < 1")
        p[0] = 1 - p.sum()
        self.outcome_p = p

    def chunk(self, ci: int, i0: int, n: int, W: Writers):
        cfg, rng = self.cfg, np.random.default_rng([self.seed, ci])
        idx = np.arange(i0, i0 + n, dtype=np.int64)
        # --- base transaction attributes
        day = rng.integers(0, self.days, n)
        hour = rng.choice(24, n, p=self.hour_p)
        sec = day * 86400 + hour * 3600 + rng.integers(0, 3600, n)
        ts = self.start + sec.astype("timedelta64[s]")
        tdate = self.start_day + day.astype("timedelta64[D]")
        types = np.array(list(cfg["txn"]["type_mix"]))
        tp = np.array(list(cfg["txn"]["type_mix"].values()), float)
        ttype = types[rng.choice(len(types), n, p=tp / tp.sum())]
        amount = np.empty(n, dtype=np.int64)
        for t in types:
            m = ttype == t
            ln = cfg["txn"]["amount_lognormal"][t]
            rupees = rng.lognormal(ln["mu"], ln["sigma"], int(m.sum()))
            amount[m] = np.rint(rupees * 100).astype(np.int64)
        ra = cfg["txn"].get("round_amounts")
        if ra:
            rnd = rng.random(n) < float(ra["share"])
            vals = np.asarray(ra["rupees"], np.int64) * 100
            amount[rnd] = vals[rng.integers(0, len(vals), int(rnd.sum()))]
        amount = np.clip(amount, cfg["txn"]["amount_min_paise"], cfg["txn"]["amount_max_paise"])
        pbank = self.banks[rng.choice(len(self.banks), n, p=self.bank_p)]
        ch = cfg["txn"]["channels"]
        chw = np.asarray(cfg["txn"]["channel_weights"], float)
        channel = np.array([c.encode() for c in ch])[rng.choice(len(ch), n, p=chw / chw.sum())]
        cust = rng.integers(0, int(cfg["ids"]["customers"]), n)
        acct = cat("XXXXXXXX", fixed_dec((cust.astype(U64) * U64(7919) + U64(13)) % U64(10000), 4))
        merch = rng.integers(0, int(cfg["ids"]["merchants"]), n)
        person = rng.integers(0, int(cfg["ids"]["customers"]), n)
        payee = np.where(ttype == "P2M", cat("MERCH", fixed_dec(merch, 6)), cat("P", fixed_dec(person, 7)))
        mob = cat("9", fixed_dec(rng.integers(0, 10 ** 9, n), 9))
        uid = _txn_ids(idx, cfg["ids"]["txn_id_prefix"], self.id_key)
        rrn = _rrn(idx, int(cfg["ids"]["rrn_digits"]), self.rrn_off)
        outcome = rng.choice(len(OUTCOMES), n, p=self.outcome_p)

        # --- settlement file of each txn; late files (not arrived at as_of) carry only clean txns
        cycle = (sec % 86400) // self.cycle_secs
        file_k = day * self.cycles + cycle
        late = ~self.file_arrived_by_as_of[file_k]
        outcome = np.where(late & (outcome != O["BUSINESS_DECLINE"]), O["SUCCESS"], outcome)
        label = np.array(OUTCOMES, dtype=object)[outcome]
        label[outcome == O["SUCCESS"]] = None
        label[late & (outcome == O["SUCCESS"])] = "LATE_FILE"

        is_ = {k: outcome == v for k, v in O.items()}
        declined = is_["BUSINESS_DECLINE"]
        dnc = is_["DEBIT_NO_CREDIT"]

        # --- switch log
        rc = cfg["responses"]
        sw_status = np.full(n, b"SUCCESS", dtype="S8")
        sw_resp = np.full(n, rc["success"].encode(), dtype="S8")
        bd = np.array([c.encode() for c in rc["business_decline"]])
        td = np.array([c.encode() for c in rc["technical_decline"]])
        sw_status[declined] = b"FAILED"
        sw_resp[declined] = bd[rng.integers(0, len(bd), int(declined.sum()))]
        dst = np.array([c.encode() for c in rc["dnc_switch_status"]])
        dw = np.asarray(rc["dnc_switch_status_weights"], float)
        sw_status[dnc] = dst[rng.choice(len(dst), int(dnc.sum()), p=dw / dw.sum())]
        sw_resp[dnc] = td[rng.integers(0, len(td), int(dnc.sum()))]
        sw_uid = uid.astype(object)
        sw_uid[is_["SWITCH_ID_MISSING"]] = None
        W.write("switch_log", {"UPI_TXN_ID": s(sw_uid), "RRN": s(rrn), "TXN_TS": ts_str(ts),
                               "AMOUNT_PAISE": pa.array(amount), "STATUS": s(sw_status),
                               "RESP_CODE": s(sw_resp), "CHANNEL": s(channel)})

        # --- NPCI settlement (split by whether the file had arrived at the recon cut-off)
        tm = cfg["timing"]
        npci_ts = ts + rng.integers(0, tm["npci_ts_jitter_s"] + 1, n).astype("timedelta64[s]")
        n_status = np.where(declined | dnc, b"FAILED", b"SUCCESS").astype("S8")
        n_resp = sw_resp.copy()
        cycle_no = (cycle + 1).astype(np.int64)
        np.add.at(self.file_counts, file_k, 1)
        for name, m in (("npci_settlement", ~late), ("npci_settlement_pending", late)):
            if m.any():
                W.write(name, {"UPI_TXN_ID": s(uid[m]), "RRN": s(rrn[m]), "TXN_TS": ts_str(npci_ts[m]),
                               "SETTLEMENT_DT": date_str(tdate[m]), "CYCLE_NO": pa.array(cycle_no[m]),
                               "AMOUNT_PAISE": pa.array(amount[m]),
                               "PAYER_BANK": pa.array([cfg["ids"]["bank_code"]] * int(m.sum())),
                               "PAYEE_BANK": s(pbank[m]), "TXN_TYPE": s(ttype[m].astype("S3")),
                               "RESP_CODE": s(n_resp[m]), "STATUS": s(n_status[m])})

        # --- CBS ledger
        nr = cfg["narration"]
        month0 = tdate.astype("datetime64[M]")
        datestr = cat(fixed_dec((tdate - month0).astype(np.int64) + 1, 2),
                      fixed_dec(month0.astype(np.int64) % 12 + 1, 2),
                      fixed_dec(tdate.astype("datetime64[Y]").astype(np.int64) + 1970, 4))   # DDMMYYYY
        fields = {"rrn": rrn, "payee": payee, "pbank": pbank, "date": datestr, "mob": mob, "txnid": uid}
        debited = ~(declined | is_["NPCI_SUCCESS_NO_CBS"])
        narr = np.empty(n, dtype=object)
        clean = debited & ~is_["NARRATION_ONLY"] & ~is_["NARRATION_NOREF"]
        for mask, key in ((clean, "clean"), (is_["NARRATION_ONLY"], "messy"), (is_["NARRATION_NOREF"], "noref")):
            if mask.any():
                narr[mask] = render_choice(rng, nr[key], {f: v[mask] for f, v in fields.items()}, int(mask.sum()))
        post_ts = ts + rng.integers(0, tm["cbs_post_lag_s"] + 1, n).astype("timedelta64[s]")
        cbs_amt = amount.copy()
        am = is_["AMOUNT_MISMATCH"]
        deltas = np.asarray(tm["amount_mismatch_deltas_paise"], np.int64)
        sign = np.where(rng.random(n) < 0.5, -1, 1)
        cbs_amt[am] = np.maximum(1, amount[am] + sign[am] * deltas[rng.integers(0, len(deltas), n)][am])
        parts = [dict(ids=_entry_ids(idx[debited], 0, self.entry_key), acct=acct[debited], ts=post_ts[debited],
                      drcr=b"DR", amt=cbs_amt[debited], narr=narr[debited])]
        dup = is_["DUPLICATE_POSTING"]
        if dup.any():
            parts.append(dict(ids=_entry_ids(idx[dup], 1, self.entry_key), acct=acct[dup],
                              ts=post_ts[dup] + np.timedelta64(int(tm["duplicate_extra_lag_s"]), "s"),
                              drcr=b"DR", amt=cbs_amt[dup], narr=narr[dup]))

        # --- DEBIT_NO_CREDIT: reversal day R, and suo-moto compensation (with injected misses)
        rev_dt = np.full(n, np.datetime64("NaT", "D"), dtype="datetime64[D]")
        comp_paid = np.full(n, -1, dtype=np.int64)          # -1 = not applicable
        if dnc.any():
            di = np.flatnonzero(dnc)
            lag = np.full(len(di), -1)
            for t in types:
                rv = cfg["reversal"][t]
                m = ttype[di] == t
                opts = np.array([-1 if v == "NEVER" else int(v) for v in rv["lag_days"]])
                w = np.asarray(rv["weights"], float)
                lag[m] = opts[rng.choice(len(opts), int(m.sum()), p=w / w.sum())]
            r_day = tdate[di] + np.maximum(lag, 0).astype("timedelta64[D]")
            r_ts = r_day.astype("datetime64[s]") + rng.integers(0, cfg["reversal"]["post_lag_s"] + 1,
                                                                len(di)).astype("timedelta64[s]")
            r_ts = np.maximum(r_ts, post_ts[di] + np.timedelta64(60, "s"))
            reversed_ = (lag >= 0) & (r_ts <= self.as_of)
            ri = di[reversed_]
            # R = calendar date the reversal posts [RBI-TAT-R-DEF]. r_ts can roll past midnight when the
            # debit itself posted after midnight (same-day reversal of a txn at ~23:58), so take the date of r_ts.
            rev_dt[ri] = r_ts[reversed_].astype("datetime64[D]")
            parts.append(dict(ids=_entry_ids(idx[ri], 2, self.entry_key), acct=acct[ri], ts=r_ts[reversed_],
                              drcr=b"CR", amt=cbs_amt[ri],
                              narr=render(nr["reversal"], {f: v[ri] for f, v in fields.items()}, len(ri))))
            tat = np.array([self.tat[rules.case_for(t.decode() if isinstance(t, bytes) else str(t))]
                            for t in ttype[ri]], dtype=np.int64)
            owed_days = np.maximum(0, (rev_dt[ri] - tdate[ri]).astype(np.int64) - tat)
            comp = cfg["compensation"]
            owed = owed_days > 0
            recorded = owed & (rng.random(len(ri)) < comp["recorded_rate"])
            under = recorded & (rng.random(len(ri)) < comp["underpaid_rate"])
            paid_days = np.where(under, owed_days - 1, owed_days)
            recorded &= paid_days > 0
            comp_paid[ri] = np.where(owed, 0, -1)
            comp_paid[ri[recorded]] = paid_days[recorded] * self.paise_per_day
            ci_ = ri[recorded]
            c_ts = r_ts[reversed_][recorded] + np.timedelta64(300, "s")
            keep = c_ts <= self.as_of
            ci_, c_ts = ci_[keep], c_ts[keep]
            comp_paid[ri[recorded][~keep]] = 0            # would post after cut-off -> not yet recorded
            if len(ci_):
                cf = {f: v[ci_] for f, v in fields.items()}
                cf["amt"] = np.char.mod("%d", comp_paid[ci_] // 100).astype("S")   # rupees, small subset only
                parts.append(dict(ids=_entry_ids(idx[ci_], 3, self.entry_key), acct=acct[ci_], ts=c_ts,
                                  drcr=b"CR", amt=comp_paid[ci_], narr=render(nr["compensation"], cf, len(ci_))))
        for p in parts:
            p["drcr"] = np.full(len(p["ids"]), p["drcr"], dtype="S2")
            p["narr"] = np.asarray(p["narr"], dtype=object)
        cbs = {k: np.concatenate([p[k] for p in parts]) for k in ("ids", "acct", "ts", "drcr", "amt", "narr")}
        order = np.argsort(cbs["ts"], kind="stable")
        W.write("cbs_ledger", {"CBS_ENTRY_ID": s(cbs["ids"][order]), "ACCOUNT_NO_MASKED": s(cbs["acct"][order]),
                               "POST_TS": ts_str(cbs["ts"][order]), "DR_CR": s(cbs["drcr"][order]),
                               "AMOUNT_PAISE": pa.array(cbs["amt"][order].astype(np.int64)),
                               "NARRATION": s(cbs["narr"][order])})

        # --- ground truth (every labelled txn; EXPECTED_CLASS None = should reconcile cleanly)
        g = np.array([l is not None for l in label])
        if g.any():
            exp = np.array([EXPECTED_CLASS.get(l) for l in label[g]], dtype=object)
            cp = comp_paid[g]
            W.write("ground_truth", {
                "UPI_TXN_ID": s(uid[g]), "INJECTED_BREAK": pa.array(list(label[g]), pa.string()),
                "EXPECTED_CLASS": pa.array(list(exp), pa.string()), "TXN_TYPE": s(ttype[g].astype("S3")),
                "TXN_DT": date_str(tdate[g]), "AMOUNT_PAISE": pa.array(amount[g]),
                "REVERSAL_DT": pa.array([None if np.isnat(d) else str(d) for d in rev_dt[g]], pa.string()),
                "COMP_PAID_PAISE": pa.array([None if v < 0 else int(v) for v in cp], pa.int64())})

    def file_log(self, out: pathlib.Path):
        n = len(self.file_expected)
        day = np.arange(n) // self.cycles
        cyc = np.arange(n) % self.cycles
        start = self.start + (np.arange(n) * self.cycle_secs).astype("timedelta64[s]")
        arrived = self.file_arrived_by_as_of
        tbl = pa.table({
            "SETTLEMENT_DT": date_str(self.start_day + day.astype("timedelta64[D]")),
            "CYCLE_NO": pa.array(cyc + 1),
            "CYCLE_START_TS": ts_str(start),
            "CYCLE_END_TS": ts_str(start + np.timedelta64(self.cycle_secs, "s")),
            "EXPECTED_TS": ts_str(self.file_expected),
            "ARRIVED_TS": pa.array([v if a else None for v, a in zip(ts_str(self.file_arrived).to_pylist(), arrived)], pa.string()),
            "RECORD_COUNT": pa.array([int(c) if a else None for c, a in zip(self.file_counts, arrived)], pa.int64()),
        })
        pacsv.write_csv(tbl, str(out / "settlement_file_log.csv"))
        # the late file(s) "arrive" later: their arrival time lives only in this manifest
        pend = [{"SETTLEMENT_DT": str(self.start_day + np.timedelta64(int(d), "D")), "CYCLE_NO": int(c) + 1,
                 "ARRIVES_TS": str(self.file_arrived[k]), "RECORD_COUNT": int(self.file_counts[k])}
                for k, (d, c, a) in enumerate(zip(day, cyc, arrived)) if not a]
        return pend


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", type=int, required=True, help="number of base UPI transactions")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--days", type=int, default=None, help="override calendar.days")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=str(ROOT / "generator" / "config.yaml"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    days = a.days or int(cfg["calendar"]["days"])
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    g = Gen(cfg, a.rows, a.seed, days)
    W = Writers(out)
    step = int(cfg["chunk_rows"])
    for ci, i0 in enumerate(range(0, a.rows, step)):
        g.chunk(ci, i0, min(step, a.rows - i0), W)
    W.close()
    pending = g.file_log(out)
    files = sorted(p for p in out.glob("*.csv"))
    manifest = {
        "synthetic": True,
        "generator_version": cfg["generator_version"], "seed": a.seed, "rows": a.rows, "days": days,
        "start_date": cfg["calendar"]["start_date"], "as_of": str(g.as_of),
        "config_sha256": sha256(pathlib.Path(a.config)), "facts_sha256": sha256(rules.FACTS_PATH),
        "row_counts": dict(W.rows, settlement_file_log=len(g.file_expected)),
        "pending_files": pending,
        "files": {p.name: sha256(p) for p in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("rows", "days", "as_of", "row_counts")}, indent=1))


if __name__ == "__main__":
    main()
