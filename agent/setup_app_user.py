"""Create (or reset) the DB user the TAT Guard backend runs as, so that it owns its own schemas and nothing else.

    python agent/setup_app_user.py        # run once as an admin user (EXA_USER), before recon/pipeline.py load

The backend used to run as the admin user. That is too much once anyone but the developer can reach the page, and the
same Exasol instance may hold other projects. This user owns RAW, RECON, AUDIT and VERIFIER and has no privilege on
any other schema, so a bug or an abuse of the page cannot read or change anything else in the database.

Env: EXA_DSN, EXA_USER, EXA_PASSWORD (admin); TATGUARD_APP_USER (default TATGUARD_APP); TATGUARD_APP_PASSWORD.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.setup_agent_user import IDENT, PASSWORD  # noqa: E402
from recon.pipeline import connect  # noqa: E402

OWNED_SCHEMAS = ("RAW", "RECON", "AUDIT", "VERIFIER")
SYSTEM_PRIVILEGES = ("CREATE SESSION", "CREATE SCHEMA", "CREATE TABLE", "CREATE VIEW", "CREATE SCRIPT", "IMPORT")


def main():
    user = os.environ.get("TATGUARD_APP_USER", "TATGUARD_APP").upper()
    pwd = os.environ.get("TATGUARD_APP_PASSWORD", "")
    if not IDENT.match(user):
        raise SystemExit(f"bad user name {user!r}")
    if not PASSWORD.match(pwd):
        raise SystemExit("TATGUARD_APP_PASSWORD must be 12-128 chars of [A-Za-z0-9_-.!@#%^*+=]")
    C = connect(admin=True)
    try:
        exists = C.execute("SELECT COUNT(*) FROM EXA_DBA_USERS WHERE USER_NAME = {u}", {"u": user}).fetchval()
        C.execute(f'{"ALTER" if exists else "CREATE"} USER {user} IDENTIFIED BY "{pwd}"')
        for p in SYSTEM_PRIVILEGES:
            C.execute(f"GRANT {p} TO {user}")
        for s in OWNED_SCHEMAS:
            C.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")     # on a fresh database this runs before the first load
            C.execute(f"ALTER SCHEMA {s} CHANGE OWNER {user}")
        owned = C.execute("SELECT SCHEMA_NAME FROM EXA_SCHEMAS WHERE SCHEMA_OWNER = {u} ORDER BY 1", {"u": user}).fetchall()
        privs = C.execute("SELECT PRIVILEGE FROM EXA_DBA_SYS_PRIVS WHERE GRANTEE = {u} ORDER BY 1", {"u": user}).fetchall()
    finally:
        C.close()
    print(f"{'updated' if exists else 'created'} {user}")
    print("owns:", [s[0] for s in owned])
    print("system privileges:", [p[0] for p in privs])


if __name__ == "__main__":
    main()
