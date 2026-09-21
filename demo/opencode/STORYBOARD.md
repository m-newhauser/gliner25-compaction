# OpenCode GLiNER-Prune Demo

The recording must use the real plugin and local small checkpoint. Do not edit
the reported reduction or substitute a replay.

## Setup

1. Use OpenCode 1.18.31 on Apple Silicon macOS.
2. Build the plugin with `npm run build`.
3. Configure the local `file://` plugin path.
4. Start OpenCode early enough for background model loading to finish.
5. Prepare a disposable tool-heavy session based on
   `fixtures/opencode/tool-heavy-session.json`.

## 30-second sequence

1. Show the long failed-test output and the later successful mutation.
2. Disconnect networking or display the offline environment.
3. Run `/gliner-prune`.
4. Hold on the summary: reduction, action counts, exact retained evidence, and
   unchanged stored history.
5. Ask OpenCode to state the failing assertion and continue verification.
6. Send a substantive new prompt and show that full context is restored.

## Claims allowed on screen

- GLiNER2.5 loads locally when OpenCode starts.
- Durable OpenCode history is unchanged.
- Canonical transcript character counts and clearly labeled estimated token
  counts.
- The measured result from the checked-in fixture and evaluation script.

Do not claim lossless pruning, zero information loss, or universal reduction.
