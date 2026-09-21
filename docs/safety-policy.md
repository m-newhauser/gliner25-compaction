# Safety policy

Pruning is allowed only after deterministic and model-output checks.

## Always preserve

- Initial and recent messages.
- Known mutating tools.
- Unknown or custom tools.
- Arbitrary shell commands.
- Question/requirement interactions.
- Unresolved errors without validated evidence.
- Low-confidence classifications.
- Invalid or mismatched evidence spans.

The shell allowlist is intentionally narrow: exact `pwd` and non-writing
`git status` invocations. Everything else is treated as potentially mutating.

## Deterministic pruning

An older `read`, `glob`, or `grep` interaction may be dropped only when a
later interaction has identical tool input, identical output, identical error
state, and no intervening mutation.

## Model-driven pruning

GLiNER returns one retention action and optional exact evidence spans.
Destructive actions must meet the configured confidence threshold and cannot
contradict reasons such as `current_dependency`, `binding_constraint`, or
`non_reproducible`.

## Failure behavior

- Sidecar timeout, crash, malformed JSON, or protocol mismatch: full context.
- Worker validation failure: host fallback or unchanged history.
- Substantive new OpenCode user goal: clear active decisions.
- Explicit OpenCode `Continue.`: carry active decisions forward.
- Native host compaction: clear stale OpenCode decisions.

Pruning is probabilistic. Do not describe it as lossless or as guaranteeing
zero information loss.
