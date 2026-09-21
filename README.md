# GLiNER2.5 Local Context

Local, extractive context pruning for coding agents. GLiNER2.5 classifies
completed tool interactions and retains exact evidence without generating a
summary or sending transcript content to an external model.

## Choose your harness

### OpenCode

Manual, non-destructive pruning of the provider-bound context.

- Package: `opencode-gliner-prune`
- Commands: setup, preview, apply, status, and reset
- Guide: [`integrations/opencode/README.md`](integrations/opencode/README.md)
- Status: developer preview for OpenCode 1.18.31 on Apple Silicon macOS

### Claude Code

Evidence-first pruning during Claude Code's native compaction lifecycle.

- Hook: `session.compact`
- Modes: shadow, apply, host fallback, or unchanged fallback
- Guide:
  [`integrations/claude-code/README.md`](integrations/claude-code/README.md)
- Status: local plugin preview

### Pi

Planned adapter using the same canonical transcript and sidecar protocol.

- Guide: [`integrations/pi/README.md`](integrations/pi/README.md)
- Status: not implemented

## Shared behavior

- Preserve recent messages, mutations, unknown tools, and arbitrary shell
  commands.
- Fail closed on low-confidence or malformed predictions.
- Rebuild excerpts only from validated original character spans.
- Preserve tool-call/result pairing.
- Default to `fastino/gliner2.5-small-v1`.

Retention actions are `keep_full`, `keep_evidence`, `keep_call_only`, and
`drop`.

## Architecture and safety

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/safety-policy.md`](docs/safety-policy.md)
- [`docs/sidecar-protocol.md`](docs/sidecar-protocol.md)
- [`docs/evaluation.md`](docs/evaluation.md)
- [`docs/compatibility.md`](docs/compatibility.md)

## Development

```sh
uv sync
uv run python scripts/download_model.py
uv run pytest

npm install
npm run typecheck
npm run test:integrations
npm run build
```

Run the real local checkpoint integration test:

```sh
GLINER25_LIVE=1 npm run test:opencode
```

Reproduce the synthetic fixture evaluation:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run python scripts/evaluate_fixture.py
```

OpenCode demo guidance lives in
[`demo/opencode/STORYBOARD.md`](demo/opencode/STORYBOARD.md).
