# HTML Guide Drift Checklist

The click-by-click HTML guide is the canonical setup procedure. The
Markdown docs under `docs/` are reference. We are **not** auto-generating
either from the other — too much of the HTML is hand-crafted (sidebar,
callout placement, progress checkboxes, in-page navigation).

Instead, every change to one source should be checked against the other
using this list.

## When you change the HTML guide

Verify the following Markdown docs still agree with it:

- [ ] `README.md` quick-start paths and clone command match HTML §04/§05.
- [ ] `docs/SETUP.md` step numbering and venv/install commands match HTML §06/§09.
- [ ] `docs/OPERATIONS.md` daily start/stop commands match HTML §22.
- [ ] `docs/TROUBLESHOOTING.md` covers every cheat-card scenario in HTML §23.
- [ ] `docs/SECURITY.md` rules match HTML §24 (numbering may differ; content shouldn't).
- [ ] `docs/MODELS.md` HF repo IDs and target paths match HTML §07/§10.
- [ ] `docs/MACOS_PREP.md` includes everything in HTML §P0 plus the deeper detail.
- [ ] `docs/BACKUP.md` is referenced in HTML §24 (security).
- [ ] `docs/MCP.md` is referenced in HTML §16.
- [ ] `docs/EXPERIMENTAL_MTP.md` matches HTML §20.

## When you change a script or config

Verify the HTML guide still references it correctly:

- [ ] If you rename a script in `scripts/`, update the HTML guide and
  `scripts/install-symlinks.sh`.
- [ ] If you change a script's CLI (args/flags), update every HTML
  code-block that invokes it.
- [ ] If you change an `mlx_lm.server` port, update the HTML §00 final
  stack map, the env examples, the sidebar TOC if it mentions port
  numbers, and all of `docs/ARCHITECTURE.md`, `docs/MODELS.md`, and the
  status scripts.

## When you change a model

- [ ] Update `docs/MODELS.md`.
- [ ] Update `configs/env.machine{1,2}.example`.
- [ ] Update `scripts/download-models-machine{1,2}.sh`.
- [ ] Update the HTML §00 final stack map.
- [ ] Update the HTML §10 / §07 download steps.
- [ ] Update the HTML §26 path appendix.

## When you change endpoints (IP/port)

The defaults live in many places; touching one without the rest creates
silent breakage. Search for the literal value:

```bash
grep -rn '127.0.0.1\|10.10.10.\|800[1-4]' \
  README.md AGENTS.md CLAUDE.md \
  docs/ configs/ scripts/ src/ mcp/ skills/
```

Update every match in the same PR.

## When you add a new section to the HTML guide

- [ ] Add a sidebar TOC entry with matching anchor.
- [ ] Renumber any downstream sections (`section-num` field).
- [ ] Renumber matching sidebar TOC entries.
- [ ] Run the small HTML validator:
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
- [ ] Confirm `data-step` attribute on each new step (needed for progress
  checkbox persistence).

## Why no auto-renderer?

We considered a Markdown→HTML pipeline. It would have:

- removed the rich callouts, copy-buttons, and progress checkboxes,
- forced one source format to dictate the other's structure,
- added a build step that itself requires testing.

A drift checklist costs ~5 minutes per PR and is auditable in code review.
The renderer would cost ~5 hours up front plus maintenance forever.
