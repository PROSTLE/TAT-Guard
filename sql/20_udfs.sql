-- Python UDF: pull a reference (our synthetic 12-digit RRN) out of a messy CBS narration.
-- The regex is passed in from RECON.SETTINGS (recon/config.yaml: matching.ref_pattern), so a bank can
-- change it without touching code. Real-world narration formats vary per bank: VERIFY per bank.
-- Narration text is untrusted data: it is only matched against a regex, never executed or interpreted.
CREATE OR REPLACE PYTHON3 SCALAR SCRIPT RECON.EXTRACT_REF(narration VARCHAR(500), pattern VARCHAR(500))
RETURNS VARCHAR(40) AS
import re
_cache = {}
def run(ctx):
    if ctx.narration is None or ctx.pattern is None:
        return None
    pat = _cache.get(ctx.pattern)
    if pat is None:
        pat = _cache[ctx.pattern] = re.compile(ctx.pattern)
    m = pat.search(ctx.narration)
    if not m:
        return None
    return m.group(1) if m.groups() else m.group(0)
/
