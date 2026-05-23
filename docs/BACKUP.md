# Backup and Disaster Recovery

What to back up, what to skip, and how to rebuild from scratch.

## Quick taxonomy of what's in `~/ai/`

| Path | Size | In git? | Back up? | Why |
|---|---|---|---|---|
| `~/ai/local-ai-stack/` | ~50 MB | yes (this repo) | no | Re-clone from GitHub. |
| `~/ai/local-ai-stack/.venv/` | ~3 GB | no (gitignored) | no | Rebuild with `uv pip install -e '.[all]'`. |
| `~/ai/local-ai-stack/.env` | small | no (gitignored) | **yes** | Has your local model paths and any tokens. |
| `~/ai/models/` | 200+ GB | no | **decide** | Re-downloadable from Hugging Face but slow. |
| `~/ai/workspaces/` | varies | each is its own git repo | per-project | Same rules as any other git repo. |
| `~/ai/workspaces/*/.agent_memory.jsonl` | small per file | gitignored in target repos | optional | History of agent runs. Useful for audit, not load-bearing. |
| `~/ai/logs/` | small | no | no | Truncate freely. |
| `~/ai/bin/` | tiny | symlinks into the repo | no | `scripts/install-symlinks.sh` rebuilds. |

## What to put in your real backup

If you're using Time Machine, Arq, restic, or similar, **include**:

- `~/ai/local-ai-stack/.env`
- `~/ai/workspaces/` (or whatever projects you keep there) — but only
  the ones not already pushed to a remote git host
- `~/.claude/skills/` if you've customized any
- `~/.gemini/antigravity-cli/skills/` if you've customized any
- `~/.gemini/antigravity-cli/mcp_config.json`
- `~/.codex/` if you've customized `config.toml`

And **exclude**:

- `~/ai/local-ai-stack/.venv/`
- `~/ai/models/` (see below)
- `~/.cache/huggingface/`
- `~/ai/logs/`
- `**/.venv/`, `**/__pycache__/`, `**/.local-ai/`

## Should you back up `~/ai/models/`?

The Heretic / Qwen weights are 200+ GB combined. They are:

- **Re-downloadable.** Every model in `docs/MODELS.md` resolves to a
  public Hugging Face repo (or a one-shot `mlx_lm.convert` step).
- **Slow to re-pull.** A clean download is hours.
- **Not in iCloud.** Make sure the directory is not under any synced
  folder (see `docs/MACOS_PREP.md`).

Options:

1. **Don't back them up.** Accept the re-download time after a wipe.
   Recommended for most setups.
2. **rsync to an external SSD periodically.** Recommended if your
   internet is slow or metered.
3. **Time Machine the directory.** Works but eats your snapshot budget.

Whichever you pick, do not back up the source HF cache
(`~/.cache/huggingface/`) — only the resolved `~/ai/models/` directory.

## Disaster recovery checklist

If a Mac wipes, here is the rebuild order:

1. macOS prep (`docs/MACOS_PREP.md`).
2. Restore `~/ai/local-ai-stack/.env` from your backup.
3. Re-clone the repo:
   ```bash
   mkdir -p ~/ai
   git clone https://github.com/zigrivers/server-setup.git ~/ai/local-ai-stack
   cd ~/ai/local-ai-stack
   uv venv .venv --python 3.12
   source .venv/bin/activate
   uv pip install -e '.[all]'   # or '.[mlx]' on Machine 2
   scripts/install-symlinks.sh
   ```
4. Restore `.env`:
   ```bash
   cp /path/to/backup/.env ~/ai/local-ai-stack/.env
   ```
5. Re-download (or restore) models:
   ```bash
   scripts/download-models-machine{1,2}.sh
   ```
6. Re-register MCP and skills:
   ```bash
   scripts/install-claude-skills.sh
   scripts/install-antigravity-skills.sh
   scripts/register-mcp-claude.sh
   scripts/register-mcp-codex.sh
   scripts/register-mcp-antigravity.sh
   ```
7. Re-install launchd agents:
   ```bash
   scripts/install-launchd-machine{1,2}.sh
   ```
8. Run the end-to-end acceptance test (HTML guide §14b).

The whole rebuild, with models already downloaded, is ~15 minutes.
With a clean model download, budget several hours per machine.

## What lives elsewhere

Things that don't live in `~/ai/` but matter for the stack:

- `~/.claude/skills/` — populated by `scripts/install-claude-skills.sh`
  from the repo. Source of truth is `skills/claude/` in the repo.
- `~/.gemini/antigravity-cli/skills/` — populated by `scripts/install-antigravity-skills.sh`
  from the repo. Source of truth is `.agents/skills/` in the repo.
- `~/.gemini/antigravity-cli/mcp_config.json` — populated by `scripts/register-mcp-antigravity.sh`.
- `~/Library/LaunchAgents/com.localai.{orchestrator,workers}.plist` —
  rendered by the install-launchd scripts.
- `~/.cache/huggingface/` — token + download cache. Safe to delete; the
  models are already in `~/ai/models/`. Your token is in
  `~/.cache/huggingface/token` and is restored by `hf auth login`.
- `~/.codex/config.toml` — Codex configuration; back up if customized.
