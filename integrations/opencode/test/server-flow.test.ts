import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { PluginInput } from "@opencode-ai/plugin";
import {
  callBridge,
  callPublishedBridge,
  resolveBridgeSocket,
} from "../src/bridge.js";
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

test("preview is cached, apply is virtual, and reset restores full context", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-flow-"));
  let analyzeCalls = 0;
  const sidecar: PruneSidecar = {
    running: true,
    setup: async () => {},
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
  const socketPath = await resolveBridgeSocket(directory);

  try {
    const preview = await callBridge(
      socketPath,
      { id: "preview-1", method: "preview", sessionID: "session-1" },
      5_000,
    );
    assert.equal(preview.ok, true);

    const applied = await callBridge(
      socketPath,
      { id: "apply-1", method: "apply", sessionID: "session-1" },
      5_000,
    );
    assert.equal(applied.ok, true);
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

test("published bridge routes to the process that owns the session", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-routing-"));
  const sidecar: PruneSidecar = {
    running: true,
    setup: async () => {},
    stop: async () => {},
    analyze: async () => ({
      decisions: [],
      characters_before: 0,
      characters_after: 0,
      reduction: 0,
      warnings: [],
      context_characters: 120,
    }),
  };
  const client = (ownedSession: string) => ({
    app: { log: async () => {} },
    session: {
      get: async ({ path }: { path: { id: string } }) =>
        path.id === ownedSession
          ? { data: { id: path.id } }
          : { error: { name: "NotFound" } },
      messages: async () => ({ data: structuredClone(messages) }),
    },
  });
  const plugin = createOpenCodeGlinerPrunePlugin(() => sidecar);
  const first = await plugin(
    {
      client: client("session-1"),
      directory,
    } as unknown as PluginInput,
    undefined,
  );
  const second = await plugin(
    {
      client: client("session-2"),
      directory,
    } as unknown as PluginInput,
    undefined,
  );
  try {
    const response = await callPublishedBridge(directory, {
      id: "route-1",
      method: "status",
      sessionID: "session-1",
    });
    assert.equal(response.ok, true);
  } finally {
    await second.dispose?.();
    await first.dispose?.();
    await rm(directory, { recursive: true });
  }
});
