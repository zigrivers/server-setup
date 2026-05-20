# Security Rules

1. Do not expose MLX, MTPLX, LM Studio, or MCP endpoints to the public internet.
2. Prefer `127.0.0.1` for Machine 1-local endpoints.
3. Prefer `10.10.10.2` Thunderbolt Bridge for Machine 1 → Machine 2 traffic.
4. Use Tailscale for remote access; do not port-forward model servers.
5. Never let agents operate on your home directory directly.
6. Use git worktrees for local execution.
7. Do not put secrets in prompts, plans, or `.agent_memory.jsonl`.
8. Keep `.env`, keys, and credentials out of git.
9. Do not auto-commit security-sensitive changes.
10. Treat MCP tools as powerful: narrow allowed roots and inspect outputs.
