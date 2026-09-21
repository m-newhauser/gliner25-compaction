# Sidecar protocol

The persistent sidecar uses one JSON object per line over stdin/stdout.
Operational logs go to stderr. Protocol version 1 supports `analyze` and
`shutdown`.

## Ready event

After loading the checkpoint:

```json
{
  "v": 1,
  "type": "ready",
  "checkpoint": "fastino/gliner2.5-small-v1"
}
```

## Analyze request

```json
{
  "v": 1,
  "type": "request",
  "id": "request-id",
  "method": "analyze",
  "payload": {
    "messages": [
      {
        "role": "assistant",
        "text": "",
        "tool_uses": [
          { "id": "call-1", "name": "read", "input": { "filePath": "x.py" } }
        ],
        "tool_results": [
          {
            "tool_use_id": "call-1",
            "text": "file contents",
            "is_error": false
          }
        ]
      }
    ],
    "goal": "Fix the parser test",
    "options": {
      "preserve_recent": 6,
      "minimum_confidence": 0.7,
      "minimum_evidence_confidence": 0.5,
      "context_characters": 120
    }
  }
}
```

## Analyze response

Successful responses contain decisions, canonical character statistics,
warnings, and the evidence-context setting. Failed responses use `ok: false`
and do not return partial decisions.

Adapters must apply decisions atomically to cloned host messages. Host-specific
metadata must never be round-tripped through the sidecar.

## Lifecycle

- One sidecar per harness process.
- Model weights load once.
- Inference requests are serialized.
- After setup, OpenCode starts the sidecar with `UV_OFFLINE`,
  `HF_HUB_OFFLINE`, and `TRANSFORMERS_OFFLINE`.
- Shutdown or process failure rejects pending requests and preserves full host
  context.
