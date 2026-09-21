# OpenCode GLiNER-Prune Demo

The recording must use the real plugin and local small checkpoint. Do not edit
the reported reduction or substitute a replay.

## Setup

1. Use OpenCode 1.18.31 on Apple Silicon macOS.
2. Build the plugin with `npm run build`.
3. Configure the local `file://` plugin path.
4. Run `/gliner-prune-setup` before recording.
5. Prepare a disposable tool-heavy session based on
   `fixtures/opencode/tool-heavy-session.json`.

## 45-second sequence

1. Show the long failed-test output and the later successful mutation.
2. Disconnect networking or display the offline environment.
3. Run `/gliner-prune-preview`.
4. Hold on the result: estimated token change, actions, and exact retained
   failure evidence.
5. Run `/gliner-prune`; the matching preview should apply immediately.
6. Ask OpenCode to state the failing assertion and continue verification.
7. Run `/gliner-prune-status` and show that pruning is active.
8. Run `/gliner-prune-reset` and show that full context is restored.

## Claims allowed on screen

- GLiNER2.5 runs locally after setup.
- Durable OpenCode history is unchanged.
- Canonical transcript character counts and clearly labeled estimated token
  counts.
- The measured result from the checked-in fixture and evaluation script.

Do not claim lossless pruning, zero information loss, or universal reduction.
