# Compatibility

## Shared core

- Python 3.11 or newer.
- `uv` for local environment management.
- Default checkpoint: `fastino/gliner2.5-small-v1`.

## OpenCode

- OpenCode 1.18.31 through the 1.18.x line.
- Apple Silicon macOS for the developer-preview package.
- Direct TUI commands use separate hyphenated names because OpenCode 1.18
  does not pass trailing slash-command arguments to plugin handlers.

## Claude Code

- Claude Code 2.1.274 or newer.
- `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`.
- Local plugin directory:
  `integrations/claude-code`.

## Pi

Not implemented. Compatibility must not be claimed until Pi’s provider-context
and tool-message APIs have been tested against the canonical protocol.

## Naming

User-facing features use “pruning.” “Compaction” is reserved for a host’s
native lifecycle or the existing repository/Python package name:

- Repository: `gliner25-compaction`
- Python import: `gliner25_context_compaction`
- OpenCode package: `opencode-gliner-prune`
- Claude plugin: `local-gliner25-pruning`
