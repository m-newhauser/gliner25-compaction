# Evaluation

Evaluation is layered so host behavior, policy, model inference, and packaging
fail independently.

## Automated checks

```sh
uv run pytest
npm run typecheck
npm run test:integrations
npm run build
```

The Python suite covers policy, exact spans, validation, Claude adaptation,
the one-shot worker, and the JSONL sidecar.

The integration suites cover:

- OpenCode message mapping and opaque metadata preservation.
- Provider-clone-only transforms.
- No-LLM TUI commands.
- Preview fingerprinting, apply, reset, and goal invalidation.
- Sidecar crash, timeout, stop, and restart behavior.
- Multi-process bridge ownership.
- Claude shadow and fallback behavior.

## Real checkpoint

```sh
GLINER25_LIVE=1 npm run test:opencode
```

This loads `fastino/gliner2.5-small-v1` locally and enforces the V1 latency
ceiling.

## Fixture evaluation

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run python scripts/evaluate_fixture.py
```

`fixtures/opencode/tool-heavy-session.json` is synthetic and sanitized. Report
its result as a fixture result, not a universal benchmark. Token counts shown
by the OpenCode plugin are estimates; canonical character counts exclude host
provider framing and metadata.

## Release claims

Do not publish reduction or latency claims unless they reproduce from a
checked-in fixture and command. Do not claim lossless pruning.
