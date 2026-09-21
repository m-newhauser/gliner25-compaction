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

Restart OpenCode. The plugin immediately prepares and loads the local model in
the background. On first launch it downloads the checkpoint; subsequent loading
and inference are local.

When context has accumulated, run:

```text
/gliner-prune
```

The completion toast reports the reduction, changed-action counts, preserved
evidence, and confirms that stored history was not modified. A new substantive
prompt automatically restores full context; exact continuations keep pruning
active.

For local development, build from the repository root and use:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "file:///absolute/path/to/gliner25-compaction/integrations/opencode"
  ]
}
```

Transcript content stays on the machine and inference is forced offline after
the checkpoint is available.

## Safety model

- Mutating tools, question answers, recent interactions, unresolved errors,
  requirements, URLs, and generated identifiers are protected.
- Unknown tools and shell commands are treated as mutating unless they match a
  narrow observational allowlist.
- Low-confidence or malformed model output resolves to `keep_full`.
- A worker crash, timeout, or invalid span sends the original full context.
- A substantive new user prompt clears active pruning automatically. Only an
  explicit continuation such as `Continue.` carries decisions forward.

Token counts shown by the plugin are estimates. Character counts cover the
canonical text and tool payloads analyzed by GLiNER, not OpenCode's provider
framing or metadata.

See the shared [architecture](../../docs/architecture.md),
[safety policy](../../docs/safety-policy.md), and
[evaluation guide](../../docs/evaluation.md).
