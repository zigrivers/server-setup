# Plan: Add Antigravity CLI Skills

## Goal
Enable the local AI stack skills (delegate-local, local-review, local-ai-status) for the Antigravity CLI (the official successor to the Gemini CLI).

## Non-goals
- No changes to Claude Code or Codex skills themselves (they continue to function as before).
- No changes to the MCP server implementation logic (`mcp/local_delegate_mcp/server.py`).
- No changes to the underlying model endpoints, ports, or Thunderbolt Bridge setup.

## Current system summary
- Currently, three skills (`delegate-local`, `local-review`, `local-ai-status`) are stored under `skills/claude/` for Claude Code.
- A shell script `scripts/install-claude-skills.sh` copies them into `~/.claude/skills/`.
- The MCP server registration is handled for Claude Code and Codex via CLI commands (`claude mcp add` and `codex mcp add`).
- There are no skills or MCP configurations for the Antigravity CLI.

## Proposed architecture
We will make the skills discoverable and usable by Antigravity CLI:
1. **Workspace Skills**: We will create `.agents/skills/` in the repository and copy the three skills there. The Antigravity CLI automatically discovers skills committed to this path when running inside this workspace.
2. **User/Global Skills**: We will write `scripts/install-antigravity-skills.sh` to copy the skills from `.agents/skills/` into the user's global skills folder at `~/.gemini/antigravity-cli/skills/`.
3. **MCP Registration**: Since Antigravity CLI uses `~/.gemini/antigravity-cli/mcp_config.json` for MCP configurations, we will write `scripts/register-mcp-antigravity.sh` using a robust Python script to merge the local-ai-delegate server configuration into `mcp_config.json` without overwriting other pre-existing servers.
4. **Audit and Remediation**: We will update the Claude slash commands (`/audit-stack` and `/fix-stack`) under `.claude/commands/` to also check for and fix the Antigravity skills and MCP configuration.

## Files expected to change

### [NEW] .agents/skills/delegate-local/SKILL.md
### [NEW] .agents/skills/local-review/SKILL.md
### [NEW] .agents/skills/local-ai-status/SKILL.md
These files will contain the same markdown content and metadata frontmatter as the Claude Code skills, ensuring compatibility with Antigravity CLI's skill format.

### [NEW] [install-antigravity-skills.sh](file:///Users/kenallred/Developer/server-setup/scripts/install-antigravity-skills.sh)
Copies skills to `~/.gemini/antigravity-cli/skills/`.

### [NEW] [register-mcp-antigravity.sh](file:///Users/kenallred/Developer/server-setup/scripts/register-mcp-antigravity.sh)
Merges the `local-ai-delegate` MCP server configuration into `~/.gemini/antigravity-cli/mcp_config.json`.

### [MODIFY] [README.md](file:///Users/kenallred/Developer/server-setup/README.md)
Update the repository file tree list to document the `.agents/skills/` directory.

### [MODIFY] [SETUP.md](file:///Users/kenallred/Developer/server-setup/docs/SETUP.md)
Update step 9 (Install Claude skills) and step 10 (Register MCP bridge) to include instructions for Antigravity CLI.

### [MODIFY] [BACKUP.md](file:///Users/kenallred/Developer/server-setup/docs/BACKUP.md)
Update to include `~/.gemini/antigravity-cli/skills/` and `~/.gemini/antigravity-cli/mcp_config.json` in the backup list and the disaster recovery checklist.

### [MODIFY] [local_ai_click_by_click_setup_guide.html](file:///Users/kenallred/Developer/server-setup/docs/html/local_ai_click_by_click_setup_guide.html)
Update Section 15 and Section 16 to document the installation of Antigravity skills and registration of its MCP bridge.

### [MODIFY] [audit-stack.md](file:///Users/kenallred/Developer/server-setup/.claude/commands/audit-stack.md)
Update the checklist to verify that global Antigravity skills and MCP registration exist.

### [MODIFY] [fix-stack.md](file:///Users/kenallred/Developer/server-setup/.claude/commands/fix-stack.md)
Update the remediation checklist to auto-install Antigravity skills if missing, and prompt to register the Antigravity MCP bridge if missing.

---

## Step-by-step tasks

1. **Create workspace skills**:
   - Create `.agents/skills/delegate-local/SKILL.md`
   - Create `.agents/skills/local-review/SKILL.md`
   - Create `.agents/skills/local-ai-status/SKILL.md`
2. **Implement scripts**:
   - Create `scripts/install-antigravity-skills.sh`
   - Create `scripts/register-mcp-antigravity.sh`
3. **Update documentation**:
   - Modify `README.md`, `docs/SETUP.md`, and `docs/BACKUP.md`.
4. **Update slash commands**:
   - Modify `.claude/commands/audit-stack.md` and `.claude/commands/fix-stack.md`.
5. **Update HTML guide**:
   - Modify `docs/html/local_ai_click_by_click_setup_guide.html`.
   - Run the HTML validator check to ensure no malformed tag errors.

## Acceptance criteria
- `scripts/install-antigravity-skills.sh` successfully copies the skills to `~/.gemini/antigravity-cli/skills/`.
- `scripts/register-mcp-antigravity.sh` successfully adds the `local-ai-delegate` configuration to `~/.gemini/antigravity-cli/mcp_config.json`.
- The HTML validator script reports no errors on `docs/html/local_ai_click_by_click_setup_guide.html`.

## Test plan

1. **Manual Verification of scripts**:
   ```bash
   ./scripts/install-antigravity-skills.sh
   # Verify output and check ~/.gemini/antigravity-cli/skills/ exists and has files
   
   ./scripts/register-mcp-antigravity.sh
   # Verify ~/.gemini/antigravity-cli/mcp_config.json has the local-ai-delegate server entry
   ```
2. **HTML Drift Check & Validation**:
   Run the python HTML validator command:
   ```bash
   python3 -c '
   from html.parser import HTMLParser
   class P(HTMLParser):
       def __init__(self): super().__init__(); self.stack=[]; self.bad=[]
       def handle_starttag(self,t,a):
           if t not in ("br","hr","meta","link","img","input"): self.stack.append(t)
       def handle_endtag(self,t):
           if not self.stack: self.bad.append(t); return
           if self.stack[-1]==t: self.stack.pop()
           else: self.bad.append((self.stack[-1],t)); self.stack.pop()
   p=P(); p.feed(open("docs/html/local_ai_click_by_click_setup_guide.html").read())
   print("unclosed:", p.stack); print("errors:", p.bad)
   '
   ```
   Ensure "unclosed" is empty and "errors" is empty.

## Rollback plan
- Delete the created files:
  - `rm -rf .agents/skills`
  - `rm -f scripts/install-antigravity-skills.sh`
  - `rm -f scripts/register-mcp-antigravity.sh`
- Revert modifications:
  - `git checkout -- README.md docs/SETUP.md docs/BACKUP.md docs/html/local_ai_click_by_click_setup_guide.html .claude/commands/`
- Clean user-level files:
  - `rm -rf ~/.gemini/antigravity-cli/skills`
  - Manually edit `~/.gemini/antigravity-cli/mcp_config.json` to remove the `local-ai-delegate` configuration (or restore from backup if available).

## Risks and edge cases
- **Config Corruption**: If the user has a malformed `mcp_config.json`, the Python JSON parser will raise an error. We handle this by logging the issue and initializing a clean configuration structure, or warning the user if it exists but cannot be parsed.
