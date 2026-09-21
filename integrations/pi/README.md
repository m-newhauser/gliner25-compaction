# Pi integration

Status: planned.

The Pi adapter should remain thin and reuse the shared Python sidecar rather
than fork pruning policy or model code.

## Required adapter responsibilities

1. Read Pi’s active provider-bound conversation.
2. Convert completed tool interactions into canonical messages.
3. Derive the current goal from recent user intent.
4. Send an `analyze` request to the local sidecar.
5. Validate and apply decisions to a cloned context.
6. Keep durable Pi history unchanged.
7. Expose setup, preview, apply, status, and reset through Pi-native UX.

## Contract

See [`../../docs/sidecar-protocol.md`](../../docs/sidecar-protocol.md) and the
OpenCode adapter in [`../opencode/src/opencode/adapter.ts`](../opencode/src/opencode/adapter.ts).

Do not promise compatibility until Pi’s message and lifecycle APIs have been
validated with real fixtures.
