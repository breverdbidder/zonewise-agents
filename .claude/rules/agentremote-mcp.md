# AgentRemote MCP Rules

## When MCP server `agentremote` is available, USE these tools:

### Session Lifecycle
- **Start**: `telegram_notify("🚀 Session Started", "Working on: {task}", "info")`
- **Every 30 min**: `telegram_send("📊 Progress: {summary}")`
- **Decisions**: `telegram_ask("{question}", [options])` — do NOT block
- **Deliverables**: `telegram_send_file("{path}", "{caption}")`
- **Complete**: `telegram_notify("✅ Done", "{summary}", "success")`
- **Errors**: `telegram_notify("🔴 Error", "{details}", "error")` — send immediately

### Rules
- Never skip session start/end notifications
- Use `telegram_ask` instead of stopping for human input
- If MCP connection fails, continue work — notifications are nice-to-have, not blockers
- Shabbat: no notifications Friday sunset → Saturday night (except data loss / security)
