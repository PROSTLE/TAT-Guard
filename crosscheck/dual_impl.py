"""Independent pandas re-implementation of the TAT Guard matcher (02_CROSS_CHECK.md §4).

Written from the class definitions in sql/15_classify.sql's header comment, NOT translated line by line
from the SQL, so the two implementations can disagree when one of them is wrong.

    python crosscheck/dual_impl.py --csv data/1m                 # offline: score vs ground_truth.csv
    python crosscheck/dual_impl.py --csv data/1m --exasol        # compare with RECON.EXCEPTIONS in Exasol

Inputs: the generator CSVs (switch_log, npci_settlement, cbs_ledger, settlement_file_log) and
recon/config.yaml. ground_truth.csv is read ONLY in the scoring section, after classification.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def classify(data: pathlib.Path) -> pd.DataFrame:
    cfg = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))
    m = cfg["matching"]
    as_of = pd.Timestamp(json.loads((data / "manifest.json").read_text(encoding="utf-8"))["as_of"])
    rd = lambda f, **kw: pd.read_csv(data / f, dtype=str, keep_default_na=False, na_values=[""], **kw)
    sw = rd("switch_log.csv")
    npci = rd("npci_settlement.csv")
    cbs = rd("cbs_ledger.csv")
    flog = rd("settlement_file_log.csv")
    for df, cols in ((sw, ["TXN_TS"]), (npci, ["TXN_TS"]), (cbs, ["POST_TS"]),
                     (flog, ["CYCLE_START_TS", "CYCLE_END_TS", "EXPECTED_TS", "ARRIVED_TS"])):
        for c in cols:
            df[c] = pd.to_datetime(df[c])
    for df in (sw, npci, cbs):
        df["AMOUNT_PAISE"] = df["AMOUNT_PAISE"].astype("int64")

    # --- switch <-> NPCI: by id+amount, else by RRN+amount within window
    sw["SW_KEY"] = np.arange(len(sw))
    by_id = sw.dropna(subset=["UPI_TXN_ID"]).merge(
        npci, on=["UPI_TXN_ID", "AMOUNT_PAISE"], suffixes=("", "_N"))
    used_n = set(by_id["UPI_TXN_ID"])
    rest_sw = sw[~sw["SW_KEY"].isin(by_id["SW_KEY"])]
    rest_n = npci[~npci["UPI_TXN_ID"].isin(used_n)]
    by_rrn = rest_sw.drop(columns=["UPI_TXN_ID"]).merge(rest_n, on=["RRN", "AMOUNT_PAISE"], suffixes=("", "_N"))
    by_rrn["DT"] = (by_rrn["TXN_TS_N"] - by_rrn["TXN_TS"]).dt.total_seconds().abs()
    by_rrn = by_rrn[by_rrn["DT"] <= m["pass2_window_s"]].sort_values("DT")
    by_rrn = by_rrn.drop_duplicates("SW_KEY").drop_duplicates("UPI_TXN_ID")
    keep = ["SW_KEY", "UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "STATUS", "RESP_CODE",
            "STATUS_N", "RESP_CODE_N", "TXN_TYPE", "PAYEE_BANK"]
    matched = pd.concat([by_id.rename(columns={"RRN_N": "_x"})[keep], by_rrn[keep]])
    txn = sw.merge(matched[["SW_KEY", "UPI_TXN_ID", "STATUS_N", "RESP_CODE_N", "TXN_TYPE", "PAYEE_BANK"]].rename(
        columns={"UPI_TXN_ID": "NID"}), on="SW_KEY", how="left")
    txn["UPI_TXN_ID"] = txn["UPI_TXN_ID"].fillna(txn["NID"])
    txn = txn.rename(columns={"STATUS": "SW_STATUS", "STATUS_N": "NPCI_STATUS", "RESP_CODE": "SW_RESP",
                              "RESP_CODE_N": "NPCI_RESP"})
    # NPCI records no switch row matched: they are transactions too (an NPCI SUCCESS with no debit is a break)
    n_only = npci[~npci["UPI_TXN_ID"].isin(set(matched["UPI_TXN_ID"]))].rename(
        columns={"STATUS": "NPCI_STATUS", "RESP_CODE": "NPCI_RESP"})
    txn = pd.concat([txn, n_only[["UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "NPCI_STATUS", "NPCI_RESP",
                                  "TXN_TYPE", "PAYEE_BANK"]]], ignore_index=True)
    txn["RESP"] = txn["SW_RESP"].fillna(txn["NPCI_RESP"])

    # --- CBS references and kinds
    pat = re.compile(m["ref_pattern"])
    def ref(s):
        if not isinstance(s, str):
            return None
        g = pat.search(s)
        return None if not g else (g.group(1) if g.groups() else g.group(0))
    cbs["REF"] = cbs["NARRATION"].map(ref)
    # credits: first narration_kinds pattern (by priority) found anywhere in the narration, else OTHER_CREDIT
    cr = cbs["DR_CR"] == "CR"
    cbs["KIND"] = "DEBIT"
    cbs.loc[cr, "KIND"] = "OTHER_CREDIT"
    untyped = cr.copy()
    for k in sorted(cfg["narration_kinds"], key=lambda k: k["priority"]):
        hit = untyped & cbs["NARRATION"].str.contains(k["pattern"], regex=True, na=False)
        cbs.loc[hit, "KIND"] = k["kind"]
        untyped &= ~hit
    rrn_set = set(txn["RRN"])
    cbs["MATCH_RRN"] = cbs["REF"].where(cbs["REF"].isin(rrn_set))

    # --- fuzzy for unmatched debits
    has_debit = set(cbs.loc[(cbs["KIND"] == "DEBIT") & cbs["MATCH_RRN"].notna(), "MATCH_RRN"])
    bd = set(cfg["response_codes"]["BUSINESS_DECLINE"])
    cand_tx = txn[~txn["RRN"].isin(has_debit) & ~txn["RESP"].isin(bd)]
    od = cbs[(cbs["KIND"] == "DEBIT") & cbs["MATCH_RRN"].isna()].reset_index()
    if len(od) and len(cand_tx):
        c = od.merge(cand_tx[["RRN", "AMOUNT_PAISE", "TXN_TS", "PAYEE_BANK"]].rename(columns={"RRN": "RRN_T"}),
                     on="AMOUNT_PAISE")
        lag = (c["POST_TS"] - c["TXN_TS"]).dt.total_seconds()
        c = c[(lag >= 0) & (lag <= m["pass4_window_s"])].copy()
        lag = (c["POST_TS"] - c["TXN_TS"]).dt.total_seconds()
        w = m["pass4_weights"]
        tok = [isinstance(b, str) and isinstance(n, str) and b in n for b, n in zip(c["PAYEE_BANK"], c["NARRATION"])]
        c["SCORE"] = w["amount"] + np.where(tok, w["bank_token"], 0) + w["time"] * (1 - lag / m["pass4_window_s"])
        c = c.sort_values(["SCORE", "RRN_T"], ascending=[False, True])
        best_c = c.drop_duplicates("index")
        best_t = c.sort_values(["SCORE", "CBS_ENTRY_ID"], ascending=[False, True]).drop_duplicates("RRN_T")
        pair = best_c.merge(best_t[["index", "RRN_T"]], on=["index", "RRN_T"])
        pair = pair[pair["SCORE"] >= m["pass4_threshold"]]
        cbs.loc[pair["index"].values, "MATCH_RRN"] = pair["RRN_T"].values

    mc = cbs[cbs["MATCH_RRN"].notna()]
    agg = mc.groupby("MATCH_RRN").agg(
        DR_CNT=("KIND", lambda k: int((k == "DEBIT").sum())),
        REV_CNT=("KIND", lambda k: int((k == "REVERSAL").sum())))
    dr_amt = mc[mc["KIND"] == "DEBIT"].groupby("MATCH_RRN")["AMOUNT_PAISE"].max().rename("DR_AMT")
    t = txn.merge(agg, left_on="RRN", right_index=True, how="left").merge(dr_amt, left_on="RRN", right_index=True, how="left")
    t[["DR_CNT", "REV_CNT"]] = t[["DR_CNT", "REV_CNT"]].fillna(0).astype(int)

    # --- settlement file of each txn
    f = flog.sort_values("CYCLE_START_TS")
    idx = np.searchsorted(f["CYCLE_START_TS"].values, t["TXN_TS"].values, side="right") - 1
    ok = (idx >= 0) & (t["TXN_TS"].values < f["CYCLE_END_TS"].values[np.clip(idx, 0, None)])
    nat = np.datetime64("NaT", "ns")
    t["F_EXP"] = pd.to_datetime(np.where(ok, f["EXPECTED_TS"].values[np.clip(idx, 0, None)], nat))
    t["F_ARR"] = pd.to_datetime(np.where(ok, f["ARRIVED_TS"].values[np.clip(idx, 0, None)], nat))

    ns, dr = t["NPCI_STATUS"], t["DR_CNT"]
    moved = (dr >= 1) | (t["SW_STATUS"] == "SUCCESS")
    no_n = ns.isna()
    conds = [(ns == "SUCCESS") & (dr == 0),
             (dr >= 1) & (ns == "FAILED"),
             dr >= 2,
             (dr == 1) & (ns == "SUCCESS") & (t["DR_AMT"] != t["AMOUNT_PAISE"]),
             no_n & t["F_ARR"].isna() & t["F_EXP"].notna() & (t["F_EXP"] <= as_of) & moved,
             no_n & t["F_ARR"].notna() & moved]
    names = ["NPCI_SUCCESS_NO_CBS", "DEBIT_NO_CREDIT", "DUPLICATE_POSTING", "AMOUNT_MISMATCH", "LATE_FILE", "NPCI_MISSING"]
    t["CLASS"] = np.select(conds, names, default="")
    t.loc[t["CLASS"] == "", "CLASS"] = None
    out = t.loc[t["CLASS"].notna(), ["UPI_TXN_ID", "RRN", "CLASS"]].copy()
    orphan = cbs[(cbs["KIND"] == "DEBIT") & cbs["MATCH_RRN"].isna()]
    out = pd.concat([out, pd.DataFrame({"UPI_TXN_ID": None, "RRN": orphan["REF"].values, "CLASS": "UNMATCHED_CBS_DEBIT",
                                        "CBS_ENTRY_ID": orphan["CBS_ENTRY_ID"].values})], ignore_index=True)
    return out


def score(pred: pd.DataFrame, data: pathlib.Path) -> pd.DataFrame:
    gt = pd.read_csv(data / "ground_truth.csv", dtype=str, keep_default_na=False, na_values=[""])
    gt = gt[gt["EXPECTED_CLASS"].notna()][["UPI_TXN_ID", "EXPECTED_CLASS"]]
    pr = pred[pred["UPI_TXN_ID"].notna()][["UPI_TXN_ID", "CLASS"]]
    j = gt.merge(pr, on="UPI_TXN_ID", how="outer")
    orphans = pred[pred["UPI_TXN_ID"].isna()]
    rows = []
    for c in sorted(set(j["EXPECTED_CLASS"].dropna()) | set(j["CLASS"].dropna()) | set(orphans["CLASS"])):
        tp = int(((j["EXPECTED_CLASS"] == c) & (j["CLASS"] == c)).sum())
        fp = int(((j["CLASS"] == c) & (j["EXPECTED_CLASS"] != c)).sum()) + int((orphans["CLASS"] == c).sum())
        fn = int(((j["EXPECTED_CLASS"] == c) & (j["CLASS"] != c)).sum())
        rows.append({"CLASS": c, "TP": tp, "FP": fp, "FN": fn,
                     "PRECISION": tp / (tp + fp) if tp + fp else None, "RECALL": tp / (tp + fn) if tp + fn else None})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--exasol", action="store_true")
    a = ap.parse_args()
    data = pathlib.Path(a.csv)
    pred = classify(data)
    print("pandas matcher vs ground truth (offline):")
    print(score(pred, data).to_string(index=False))
    if a.exasol:
        import pyexasol
        C = pyexasol.connect(dsn=os.environ["EXA_DSN"], user=os.environ["EXA_USER"], password=os.environ["EXA_PASSWORD"])
        # read every column as text, like the CSVs above: an all-digit RRN must not become an int (or lose zeros)
        exa = C.export_to_pandas('SELECT "UPI_TXN_ID", "RRN", "CBS_ENTRY_ID", "CLASS" FROM "RECON"."EXCEPTIONS"',
                                 callback_params={"dtype": str, "keep_default_na": False, "na_values": [""]})
        key = lambda df: df["UPI_TXN_ID"].fillna("RRN:" + df["RRN"].fillna("") + "|" + df.get("CBS_ENTRY_ID", pd.Series(index=df.index, dtype=str)).fillna(""))
        pred["K"], exa["K"] = key(pred), key(exa)
        mg = exa.merge(pred, on="K", how="outer", suffixes=("_exa", "_pd"), indicator=True)
        dis = mg[(mg["_merge"] != "both") | (mg["CLASS_exa"] != mg["CLASS_pd"])]
        print(f"\nExasol vs pandas: {len(exa)} vs {len(pred)} exceptions, {len(dis)} disagreements")
        if len(dis):
            print(dis.head(20).to_string(index=False))
        sys.exit(1 if len(dis) else 0)


if __name__ == "__main__":
    main()
