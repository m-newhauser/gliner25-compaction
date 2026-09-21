import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { PluginInput } from "@opencode-ai/plugin";
import { bridgeSocketPath, callBridge } from "../src/bridge.js";
import type { OpenCodeMessage } from "../src/opencode/adapter.js";
import {
  createOpenCodeGlinerPrunePlugin,
  type PruneSidecar,
} from "../src/server.js";

const messages = [
  {
    info: { id: "user-1", sessionID: "session-1", role: "user" },
    parts: [{ id: "text-1", type: "text", text: "Inspect the parser." }],
  },
  {
    info: { id: "assistant-1", sessionID: "session-1", role: "assistant" },
    parts: [
      {
        id: "tool-1",
        type: "tool",
        callID: "call-1",
        tool: "read",
        state: {
          status: "completed",
          input: { filePath: "parser.py" },
          output: "full parser contents",
        },
      },
    ],
  },
];

test("startup prepares the model and apply is virtual", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-flow-"));
  let analyzeCalls = 0;
  let setupCalls = 0;
  const sidecar: PruneSidecar = {
    running: true,
    setup: async () => {
      setupCalls += 1;
    },
    stop: async () => {},
    analyze: async () => {
      analyzeCalls += 1;
      return {
        decisions: [
          {
            tool_use_id: "call-1",
            action: "keep_call_only",
            confidence: 0.95,
            reasons: ["safely_rerunnable"],
            evidence: [],
          },
        ],
        characters_before: 100,
        characters_after: 20,
        reduction: 0.8,
        warnings: [],
        context_characters: 120,
      };
    },
  };
  const client = {
    app: { log: async () => {} },
    session: {
      get: async () => ({ data: { id: "session-1" } }),
      messages: async () => ({ data: structuredClone(messages) }),
    },
  };
  const plugin = createOpenCodeGlinerPrunePlugin(() => sidecar);
  const hooks = await plugin(
    { client, directory } as unknown as PluginInput,
    undefined,
  );
  const socketPath = bridgeSocketPath(directory);

  try {
    const applied = await callBridge(
      socketPath,
      { id: "apply-1", method: "apply", sessionID: "session-1" },
      5_000,
    );
    assert.equal(applied.ok, true);
    if (applied.ok) {
      assert.match(applied.result.message, /^Context pruned by 80\.0%/);
      assert.match(applied.result.message, /1\/1 tool results changed/);
      assert.match(applied.result.message, /Dropped 0 · reduced 0 · omitted 1/);
      assert.match(applied.result.message, /Stored history unchanged/);
    }
    assert.equal(setupCalls, 1);
    assert.equal(analyzeCalls, 1);

    const transformed = { messages: structuredClone(messages) };
    await hooks["experimental.chat.messages.transform"]?.(
      {},
      transformed as never,
    );
    assert.equal(
      (transformed.messages as unknown as OpenCodeMessage[])[1]?.parts[0]?.state
        ?.output,
      "[tool result omitted; re-run if needed]",
    );

    const continued = {
      messages: [
        ...structuredClone(messages),
        {
          info: { id: "user-2", sessionID: "session-1", role: "user" },
          parts: [{ id: "text-2", type: "text", text: "Continue." }],
        },
      ],
    };
    await hooks["experimental.chat.messages.transform"]?.(
      {},
      continued as never,
    );
    assert.equal(
      (continued.messages as unknown as OpenCodeMessage[])[1]?.parts[0]?.state
        ?.output,
      "[tool result omitted; re-run if needed]",
    );

    const changedGoal = {
      messages: [
        ...structuredClone(messages),
        {
          info: { id: "user-3", sessionID: "session-1", role: "user" },
          parts: [
            {
              id: "text-3",
              type: "text",
              text: "Now audit the authentication boundary.",
            },
          ],
        },
      ],
    };
    await hooks["experimental.chat.messages.transform"]?.(
      {},
      changedGoal as never,
    );
    assert.equal(
      (changedGoal.messages as unknown as OpenCodeMessage[])[1]?.parts[0]?.state
        ?.output,
      "full parser contents",
    );

    await callBridge(
      socketPath,
      { id: "reset-1", method: "reset", sessionID: "session-1" },
      5_000,
    );
    const restored = { messages: structuredClone(messages) };
    await hooks["experimental.chat.messages.transform"]?.(
      {},
      restored as never,
    );
    assert.equal(
      (restored.messages as unknown as OpenCodeMessage[])[1]?.parts[0]?.state
        ?.output,
      "full parser contents",
    );
  } finally {
    await hooks.dispose?.();
    await rm(directory, { recursive: true });
  }
});
