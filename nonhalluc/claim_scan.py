# nonhalluc/claim_scan.py — usage: python claim_scan.py README.md deck_text.md ...
# Source: 04_NON_HALLUCINATOR.md §4. Flags numbers not tagged with a fact ID, ASSUMPTION, MEASURED or DESIGN.
import re, sys, yaml, pathlib
sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252 and crash on '₹'

TAG = re.compile(r'\[(?:[A-Z0-9]+-[A-Z0-9-]+|ASSUMPTION|MEASURED|DESIGN)\]')
# Fix vs 04 §4 original: '%' is not a word char, so the original trailing \b never matched "13% today".
NUM = re.compile(r'(₹\s?[\d,]+(?:\.\d+)?\s*(?:lakh|crore|L|Cr)?|\b\d[\d,]*(?:\.\d+)?\s*(?:%|(?:bn|billion|million|crore|lakh)\b)|\b\d{1,3}(?:,\d{2,3})+\b)', re.I)
FACTS = pathlib.Path(__file__).resolve().parents[1] / "facts.yaml"   # independent of the working directory
ids = {f["id"] for f in yaml.safe_load(open(FACTS, encoding="utf-8"))["facts"]}

bad = 0
for path in sys.argv[1:]:
    for n, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith(("```", "#!", "    ")):   # skip code-ish lines
            continue
        nums = NUM.findall(line)
        if not nums:
            continue
        tags = TAG.findall(line)
        unknown = [t for t in tags if t.strip("[]") not in ids | {"ASSUMPTION", "MEASURED", "DESIGN"}]
        if not tags or unknown:
            bad += 1
            print(f"{path}:{n}: UNSOURCED {nums} {('unknown tags ' + str(unknown)) if unknown else ''}\n    {line.strip()}")
print(f"\n{bad} unsourced line(s)")
sys.exit(1 if bad else 0)
