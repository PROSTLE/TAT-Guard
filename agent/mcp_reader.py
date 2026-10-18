"""Read-only SQL through the official Exasol MCP server (exasol-mcp-server, pinned in docs/SETUP.md §4).

The server is launched as a stdio subprocess with uvx and logs in as the read-only DB user created by
agent/setup_agent_user.py. Read-only is enforced twice:
  1. MCP settings: enable_read_query=true, enable_write_query=false. execute_exasol_query accepts only a
     single SELECT (the server parses it with sqlglot and rejects anything else, including SELECT INTO).
  2. The DB user has CREATE SESSION + SELECT on RAW, RECON, AUDIT only. It has no write privilege and no
     access to VERIFIER (ground truth).

Env: EXA_DSN, TATGUARD_AGENT_USER (default TATGUARD_AGENT), TATGUARD_AGENT_PASSWORD.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import threading
import time

from mcp import Client, StdioServerParameters, stdio_client

LOG = pathlib.Path(__file__).resolve().parents[1] / "logs" / "mcp_server.log"   # server stderr (banner, warnings)

MCP_SERVER_SPEC = "exasol-mcp-server==2.2.0"      # DESIGN: pinned, see docs/SETUP.md §4
MCP_SETTINGS = {                                    # keys/defaults from mcp-server doc/user_guide/tool_setup.rst
    "enable_read_query": True,
    "enable_write_query": False,
    "views": {"enable": True},
    "default_row_limit": 1000,                      # DESIGN: guard against unbounded results
    "query_result_format": "tabular",
    "enable_preprocessor_tools": False,             # set_exasol_preprocessor is not needed and changes session state
}


class McpError(RuntimeError):
    pass


class McpReader:
    def __init__(self, timeout_s: float = 120):
        self.timeout_s = timeout_s
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._client: Client | None = None
        self._err: BaseException | None = None
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="mcp-reader").start()
        if not self._ready.wait(timeout_s):
            raise McpError("MCP server did not start in time")
        if self._err:
            raise McpError(f"MCP server failed to start: {self._err}")

    def _params(self) -> StdioServerParameters:
        env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP",
                                                                 "USERPROFILE", "LOCALAPPDATA", "APPDATA",
                                                                 "HOME", "HOMEDRIVE", "HOMEPATH")}
        env.update({
            "EXA_DSN": os.environ["EXA_DSN"],
            "EXA_USER": os.environ.get("TATGUARD_AGENT_USER", "TATGUARD_AGENT"),
            "EXA_PASSWORD": os.environ["TATGUARD_AGENT_PASSWORD"],
            "EXA_MCP_SETTINGS": json.dumps(MCP_SETTINGS),
            "EXASOL_TELEMETRY_DISABLE": "1",
        })
        return StdioServerParameters(command="uvx", args=["--from", MCP_SERVER_SPEC, "exasol-mcp-server"], env=env)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._stop = asyncio.Event()
        LOG.parent.mkdir(exist_ok=True)
        try:
            with open(LOG, "a", encoding="utf-8") as errlog:
                async with Client(stdio_client(self._params(), errlog=errlog)) as client:
                    self._client = client
                    self.tools = sorted(t.name for t in (await client.list_tools()).tools)
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as e:  # surfaced to the constructor
            self._err = e
            self._ready.set()

    async def _call(self, name: str, args: dict):
        return await self._client.call_tool(name, args)

    def call(self, name: str, args: dict):
        with self._lock:
            fut = asyncio.run_coroutine_threadsafe(self._call(name, args), self._loop)
            return fut.result(self.timeout_s)

    def query(self, sql: str) -> dict:
        """Run one SELECT through execute_exasol_query. Returns {sql, columns, rows, ms}. Raises McpError."""
        t0 = time.perf_counter()
        res = self.call("execute_exasol_query", {"query": sql})
        ms = round((time.perf_counter() - t0) * 1000)
        text = " ".join(getattr(c, "text", "") for c in res.content)
        if res.is_error:
            raise McpError(text or "query refused")
        data = res.structured_content
        if isinstance(data, dict) and "result" in data and "columns" not in data:
            data = data["result"]
        if not (isinstance(data, dict) and "columns" in data):
            data = json.loads(text)
        return {"sql": sql, "columns": data["columns"], "rows": data["rows"], "ms": ms}

    def close(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
