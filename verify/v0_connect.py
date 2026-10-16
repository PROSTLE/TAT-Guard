# verify/v0_connect.py — Source: 03_VERIFIER.md V0.
# Runs SELECT CURRENT_TIMESTAMP and prints the server version. Credentials from env vars only.
import os, pyexasol
C = pyexasol.connect(dsn=os.environ["EXA_DSN"], user=os.environ["EXA_USER"], password=os.environ["EXA_PASSWORD"])
print(C.execute("SELECT CURRENT_TIMESTAMP").fetchval())
print(C.execute("SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME='databaseProductVersion'").fetchval())
