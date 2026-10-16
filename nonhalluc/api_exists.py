# nonhalluc/api_exists.py — usage: python api_exists.py pyexasol ExaConnection.import_from_pandas
# Source: 04_NON_HALLUCINATOR.md §3. Proves a library attribute exists before we use it.
import importlib, sys, inspect
mod_name, attr_path = sys.argv[1], sys.argv[2]
obj = importlib.import_module(mod_name)
for part in attr_path.split("."):
    if not hasattr(obj, part):
        print(f"MISSING: {mod_name}.{attr_path} (failed at '{part}')"); sys.exit(1)
    obj = getattr(obj, part)
print("EXISTS:", f"{mod_name}.{attr_path}")
try:
    print("SIGNATURE:", inspect.signature(obj))
except (TypeError, ValueError):
    pass
