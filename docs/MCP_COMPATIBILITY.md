# Exasol MCP Server Compatibility

TAT Guard requires **exasol-mcp-server >= 2.2.0**.

## Verified Versions

| MCP Server Version | Status     | Notes |
| ------------------ | ---------- | ----- |
| 2.2.0              | Tested     | Used during initial development |
| 2.1.x              | Untested   | May work but not guaranteed |
| < 2.1              | Unsupported| Missing required query capabilities |

## Key Dependencies

- The agent uses `read query` MCP tool for SELECT-only access
- Schema introspection requires `list schemas` and `describe table`
- Connection parameters are passed via environment variables

## Checking Your Version

```bash
exasol mcp-server --version
```
