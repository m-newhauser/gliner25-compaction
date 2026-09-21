# Architecture

The repository has one host-neutral pruning engine and separate harness
adapters.

```text
Harness transcript
  → harness adapter
  → canonical messages
  → GLiNER analyzer + deterministic policy
  → validated retention decisions
  → cloned provider context
```

## Shared Python core

`src/gliner25_context_compaction/` owns:

- Canonical message and tool-interaction types.
- Schema-conditioned classification and evidence extraction.
- Deterministic mutation, recency, confidence, and duplicate-read policy.
- Exact-span reconstruction.
- Post-analysis validation.
- A persistent JSONL sidecar and a one-shot Claude worker.

The core has no OpenCode or Pi imports. `claude.py` is retained as a
compatibility boundary for the existing Claude message shape.

## OpenCode

The OpenCode integration has two entrypoints:

- A server plugin transforms only OpenCode’s cloned provider context.
- A TUI plugin exposes no-LLM setup, preview, apply, status, and reset
  commands.

A private Unix-socket bridge connects the TUI process to the server process.
The server owns session state and one warm Python sidecar.

## Claude Code

Claude Code calls the TypeScript function hook during `session.compact`. The
hook invokes a supervised one-shot Python worker and either:

- Logs the proposal in shadow mode.
- Returns validated pruned messages.
- Delegates to Claude’s native compactor.
- Leaves history unchanged.

## Pi

Pi will reuse the canonical transcript and sidecar protocol. Only message
mapping, lifecycle wiring, and user interface behavior should be
harness-specific.
