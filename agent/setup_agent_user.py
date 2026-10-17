"""Create (or reset) the read-only DB user the agent's MCP server logs in as.

    python agent/setup_agent_user.py        # run as an admin user (EXA_USER), after recon/pipeline.py load

Privileges (Exasol docs, CREATE USER / GRANT pages): CREATE SESSION, plus SELECT on schemas RAW, RECON, AUDIT.
"When granting an object privilege on a schema, this privilege is applied to all contained schema objects",
so the grant survives the CREATE OR REPLACE TABLE statements in sql/. No INSERT/UPDATE/DELETE, no DDL, and no
access to VERIFIER (ground truth).
Env: EXA_DSN, EXA_USER, EXA_PASSWORD (admin); TATGUARD_AGENT_USER (default TATGUARD_AGENT); TATGUARD_AGENT_PASSWORD.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recon.pipeline import connect  # noqa: E402

READ_SCHEMAS = ("RAW", "RECON", "AUDIT")
IDENT = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
PASSWORD = re.compile(r"^[A-Za-z0-9_\-.!@#%^*+=]{12,128}$")   # no quotes -> safe inside "..."


def main():
    user = os.environ.get("TATGUARD_AGENT_USER", "TATGUARD_AGENT").upper()
    pwd = os.environ.get("TATGUARD_AGENT_PASSWORD", "")
    if not IDENT.match(user):
        raise SystemExit(f"bad user name {user!r}")
    if not PASSWORD.match(pwd):
        raise SystemExit("TATGUARD_AGENT_PASSWORD must be 12-128 chars of [A-Za-z0-9_-.!@#%^*+=]")
    C = connect()
    try:
        exists = C.execute("SELECT COUNT(*) FROM EXA_DBA_USERS WHERE USER_NAME = {u}", {"u": user}).fetchval()
        C.execute(f'{"ALTER" if exists else "CREATE"} USER {user} IDENTIFIED BY "{pwd}"')
        C.execute(f"GRANT CREATE SESSION TO {user}")
        for s in READ_SCHEMAS:
            C.execute(f"GRANT SELECT ON {s} TO {user}")
        privs = C.execute("SELECT PRIVILEGE FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE = {u} ORDER BY 1", {"u": user}).fetchall()
        objs = C.execute("SELECT OBJECT_SCHEMA, OBJECT_NAME, PRIVILEGE FROM EXA_DBA_OBJ_PRIVS WHERE GRANTEE = {u} ORDER BY 1, 2, 3",
                         {"u": user}).fetchall()
    finally:
        C.close()
    print(f"{'updated' if exists else 'created'} {user}")
    print("system privileges:", [p[0] for p in privs])
    print("object privileges:", objs)


if __name__ == "__main__":
    main()
