# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in TAT Guard, please report it responsibly:

1. **Do not** open a public issue
2. Email: harshitaryan21@gmail.com
3. Include a description and steps to reproduce
4. Allow up to 72 hours for an initial response

## Security Controls

- Agent operates through MCP with SELECT-only database access
- Grounding guard verifies all numbers in agent responses
- Actions use fixed SQL templates (no LLM-generated SQL)
- Human approval is mandatory for every state change
- UI binds to 127.0.0.1 only with CORS and Origin checks
- All executed actions are logged to AUDIT.ACTION_LOG
