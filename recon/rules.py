"""Regulatory constants for TAT Guard, loaded from facts.yaml at runtime (single source of truth).

Nothing regulatory is typed into code. If a fact is missing, or its status is not 'verified',
loading fails loudly instead of falling back to a remembered value (04_NON_HALLUCINATOR.md rules 1 and 6).
"""
from __future__ import annotations

import functools
import pathlib

import yaml

FACTS_PATH = pathlib.Path(__file__).resolve().parents[1] / "facts.yaml"

# case name used across TAT Guard -> fact ID holding its TAT (in days)
TAT_FACT_IDS = {"UPI_P2P": "RBI-TAT-UPI-P2P", "UPI_P2M": "RBI-TAT-UPI-P2M", "IMPS": "RBI-TAT-IMPS"}
COMP_FACT_ID = "RBI-TAT-COMP"
DAYCOUNT_FACT_ID = "RBI-TAT-DAYCOUNT"   # must be verified: our day arithmetic assumes calendar dates


class FactError(RuntimeError):
    pass


@functools.lru_cache(maxsize=None)
def _facts(path: str = str(FACTS_PATH)) -> dict:
    with open(path, encoding="utf-8") as fh:
        return {f["id"]: f for f in yaml.safe_load(fh)["facts"]}


def _verified(fid: str) -> dict:
    f = _facts().get(fid)
    if f is None:
        raise FactError(f"fact {fid} not in facts.yaml")
    if f.get("status") != "verified":
        raise FactError(f"fact {fid} has status {f.get('status')!r}, not 'verified'")
    return f


def tat_days() -> dict[str, int]:
    _verified(DAYCOUNT_FACT_ID)
    return {case: int(_verified(fid)["value"]) for case, fid in TAT_FACT_IDS.items()}


def rupees_per_day() -> int:
    return int(_verified(COMP_FACT_ID)["value"])


def paise_per_day() -> int:
    return rupees_per_day() * 100


def case_for(txn_type: str, rail: str = "UPI") -> str:
    """Map (rail, TXN_TYPE) to a TAT case name, e.g. ('UPI', 'P2M') -> 'UPI_P2M'."""
    case = "IMPS" if rail == "IMPS" else f"{rail}_{txn_type}"
    if case not in TAT_FACT_IDS:
        raise KeyError(f"no TAT rule for {case}")
    return case
