# Claude Code integration

This plugin runs local GLiNER2.5 pruning when Claude Code enters its native
`session.compact` lifecycle. “Compaction” refers to the Claude lifecycle;
the plugin itself performs extractive pruning rather than generating a
summary.

## Requirements

- Claude Code 2.1.274 or newer
- Function hooks enabled
- The repository Python environment created with `uv sync`
- The small checkpoint cached with `uv run python scripts/download_model.py`

## Run locally

From the repository root:

```sh
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1
export GLINER_PRUNING_PYTHON="$PWD/.venv/bin/python"
claude --plugin-dir ./integrations/claude-code
```

Optional capture path:

```sh
export GLINER_PRUNING_CAPTURE_PATH="$PWD/.tmp/claude-pruning.json"
```

## Behavior

The plugin defaults to shadow mode. It runs the local worker and logs the
proposed deletion manifest without replacing Claude’s history. Set
`shadowMode` to `false` after reviewing the output.

Eligible interactions are analyzed in batches. Low-confidence decisions,
mutations, unknown tools, and arbitrary shell commands remain full. The worker
validates transcript structure and evidence spans before returning a
replacement.

Failures delegate to Claude’s native compactor by default. Set `fallback` to
`unchanged` to retain the original transcript instead.

## Naming

User-facing names use “pruning”:

- Plugin: `local-gliner25-pruning`
- Hook: `gliner25-pruning.ts`
- Environment: `GLINER_PRUNING_*`

The shared Python import remains `gliner25_context_compaction` for repository
and package continuity.
