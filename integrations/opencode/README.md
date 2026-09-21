# opencode-gliner-prune

Local, non-destructive context pruning for OpenCode using
`fastino/gliner2.5-small-v1`.

The plugin analyzes completed tool interactions locally, keeps recent and
mutating operations, preserves exact evidence spans, and changes only the
cloned context sent to the model. OpenCode's stored session remains unchanged.

## Requirements

- Apple Silicon macOS
- OpenCode 1.18.31
- `uv`

## Install

Add the npm package to `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-gliner-prune"]
}
```

Restart OpenCode, then run:

```text
/gliner-prune-setup
/gliner-prune-preview
/gliner-prune
```

Other commands:

- `/gliner-prune-status`
- `/gliner-prune-reset`

For local development, build from the repository root and use:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "file:///absolute/path/to/gliner25-compaction/integrations/opencode"
  ]
}
```

OpenCode 1.18's direct TUI command API does not pass trailing slash-command
arguments to plugin handlers. V1 therefore uses separate hyphenated commands
instead of `/gliner-prune preview`; this keeps every plugin command out of the
LLM prompt path.

Setup downloads and warms the small checkpoint. Transcript content stays on
the machine; subsequent inference is forced offline.

## Safety model

- Mutating tools, question answers, recent interactions, unresolved errors,
  requirements, URLs, and generated identifiers are protected.
- Unknown tools and shell commands are treated as mutating unless they match a
  narrow observational allowlist.
- Low-confidence or malformed model output resolves to `keep_full`.
- A worker crash, timeout, or invalid span sends the original full context.
- Preview decisions are cached and promoted only when the transcript
  fingerprint still matches.
- Reset immediately restores full provider context because durable history was
  never modified.
- A substantive new user prompt clears active pruning automatically. Only an
  explicit continuation such as `Continue.` carries decisions forward.

Token counts shown by the plugin are estimates. Character counts cover the
canonical text and tool payloads analyzed by GLiNER, not OpenCode's provider
framing or metadata.

See the shared [architecture](../../docs/architecture.md),
[safety policy](../../docs/safety-policy.md), and
[evaluation guide](../../docs/evaluation.md).
