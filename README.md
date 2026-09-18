# GLiNER2.5 Context Compaction

Experimental verbatim context compaction for coding-agent transcripts.
GLiNER2.5 chooses one retention action per completed tool interaction and
extracts exact evidence spans when a full result is unnecessary.

## V1 policy

- Keep the initial and most recent messages.
- Keep mutating tool calls and results.
- Extract evidence before classification and promote validated high-confidence
  diagnostics, requirements, URLs, and generated identifiers.
- Fail closed on uncertain model predictions.
- Rebuild excerpts only from original character spans.
- Preserve tool-call/result pairing.

Retention actions are `keep_full`, `keep_evidence`, `keep_call_only`, and
`drop`. A generic transcript model is the core format; `claude.py` converts
Claude Code session messages at the boundary.

## Setup

```sh
uv sync
uv run python scripts/download_model.py
uv run pytest
```

The default local checkpoint is `fastino/gliner2.5-base-v1`.

## Status

This first milestone contains the transcript model, Claude adapter, GLiNER
classification/evidence schemas, deterministic compactor, and unit tests with
a fake analyzer. Host hook integration and domain tuning are intentionally
deferred.
