# nonhalluc/sql_probe.py — runs a statement in a rolled-back transaction and reports the exact error
# Source: 04_NON_HALLUCINATOR.md §3. Usage: python sql_probe.py "SELECT HASH_MD5('x')"
import os, sys, pyexasol
C = pyexasol.connect(dsn=os.environ["EXA_DSN"], user=os.environ["EXA_USER"],
                     password=os.environ["EXA_PASSWORD"], autocommit=False)
sql = sys.argv[1]
try:
    C.execute(sql); print("OK:", sql)
except pyexasol.ExaQueryError as e:
    print("ERROR:", e.code, e.message); sys.exit(1)
finally:
    C.rollback()
