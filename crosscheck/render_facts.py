"""Render docs/FACTS.md from facts.yaml (01_BUILD_PLAN.md Phase 6). Never edit FACTS.md by hand.

    python crosscheck/render_facts.py
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def cell(v) -> str:
    if v is None:
        return ""
    s = ", ".join(f"{k}: {x}" for k, x in v.items()) if isinstance(v, dict) else str(v)
    return s.replace("|", "\\|").replace("\n", " ").strip()


def main():
    facts = yaml.safe_load(open(ROOT / "facts.yaml", encoding="utf-8"))["facts"]
    lines = ["# FACTS", "",
             "Generated from [facts.yaml](../facts.yaml) by `python crosscheck/render_facts.py`. Do not edit by hand.",
             "",
             "`verified` = the text was read at the URL; the Note column says when a source is secondary or dated. "
             "`VERIFY` = not yet confirmed; such facts must not be stated as true.", "",
             "| ID | Claim / value | Quote | Status | Note | Source |", "|---|---|---|---|---|---|"]
    for f in facts:
        claim = cell(f.get("claim")) or cell(f.get("value"))
        if f.get("claim") and f.get("value") is not None:
            claim += f" (value: {cell(f['value'])})"
        src = f"[link]({f['url']})" if f.get("url") else ""
        lines.append(f"| `{f['id']}` | {claim} | {cell(f.get('quote'))} | {f.get('status')} | {cell(f.get('note'))} | {src} |")
    out = ROOT / "docs" / "FACTS.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(facts)} facts)")


if __name__ == "__main__":
    main()
