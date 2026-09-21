import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { TuiPluginApi } from "@opencode-ai/plugin/tui";
import {
  bridgeSocketPath,
  callBridge,
  callPublishedBridge,
  publishBridge,
  resolveBridgeSocket,
  resolveBridgeSockets,
  startBridge,
  stopBridge,
} from "../src/bridge.js";
import { createMessageTransform } from "../src/server.js";
import { registerGlinerPruneCommand } from "../src/tui.js";

test("bridge serves a local status request", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-bridge-"));
  const socketPath = bridgeSocketPath(directory);
  const server = await startBridge(socketPath, async (request) => ({
    id: request.id,
    ok: true,
    result: { message: "ready" },
  }));
  try {
    const response = await callBridge(socketPath, {
      id: "request-1",
      method: "status",
    });
    assert.deepEqual(response, {
      id: "request-1",
      ok: true,
      result: { message: "ready" },
    });
  } finally {
    await stopBridge(server, socketPath);
    await rm(directory, { recursive: true });
  }
});

test("bridge instances do not unlink each other's sockets", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-owners-"));
  const firstPath = bridgeSocketPath(directory, "first");
  const secondPath = bridgeSocketPath(directory, "second");
  const firstHandler = async (request: { id: string }) => ({
    id: request.id,
    ok: true as const,
    result: { message: "first" },
  });
  const secondHandler = async (request: { id: string }) => ({
    id: request.id,
    ok: false as const,
    error: "session not found",
  });
  const first = await startBridge(firstPath, firstHandler);
  const second = await startBridge(secondPath, secondHandler);
  try {
    await publishBridge(directory, firstPath);
    await publishBridge(directory, secondPath);
    assert.deepEqual(
      new Set(await resolveBridgeSockets(directory)),
      new Set([firstPath, secondPath]),
    );
    assert.deepEqual(
      await callPublishedBridge(directory, {
        id: "owner-1",
        method: "status",
        sessionID: "session-1",
      }),
      {
        id: "owner-1",
        ok: true,
        result: { message: "first" },
      },
    );
    await stopBridge(first, firstPath, directory);
    assert.equal(await resolveBridgeSocket(directory), secondPath);
    await stopBridge(second, secondPath, directory);
    await assert.rejects(resolveBridgeSocket(directory));
  } finally {
    if (first.listening) await stopBridge(first, firstPath);
    if (second.listening) await stopBridge(second, secondPath);
    await rm(directory, { recursive: true });
  }
});

test("message transform edits only the provider-bound clone", async () => {
  const original = [
    {
      info: { id: "message-1", sessionID: "session-1", role: "assistant" },
      parts: [
        {
          id: "part-1",
          messageID: "message-1",
          sessionID: "session-1",
          type: "tool",
          callID: "call-1",
          tool: "read",
          state: { status: "completed", input: {}, output: "full output" },
        },
      ],
    },
  ];
  const providerBound = structuredClone(original);
  const transform = createMessageTransform(
    new Map([
      [
        "session-1",
        {
          active: {
            result: {
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
            },
          },
        },
      ],
    ]),
  );

  const output = { messages: providerBound as never };
  await transform({}, output);

  assert.equal(
    (output.messages as unknown as typeof providerBound)[0]?.parts[0]?.state
      .output,
    "[tool result omitted; re-run if needed]",
  );
  assert.equal(original[0]?.parts[0]?.state.output, "full output");
});

test("TUI slash command reports status without submitting a prompt", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-tui-"));
  const socketPath = bridgeSocketPath(directory);
  const server = await startBridge(socketPath, async (request) => ({
    id: request.id,
    ok: true,
    result: { message: "GLiNER prune ready" },
  }));
  await publishBridge(directory, socketPath);
  let registered:
    | {
        onSelect?: () => void | Promise<void>;
      }
    | undefined;
  const toasts: Array<{ message: string }> = [];
  let clientAccesses = 0;

  const api = {
    command: {
      register: (
        callback: () => Array<{ onSelect?: () => void | Promise<void> }>,
      ) => {
        registered = callback()[0];
        return () => {};
      },
    },
    route: { current: { name: "session", params: { sessionID: "session-1" } } },
    state: { path: { directory } },
    ui: { toast: (toast: { message: string }) => toasts.push(toast) },
    lifecycle: { onDispose: () => () => {} },
    client: new Proxy(
      {},
      {
        get() {
          clientAccesses += 1;
          throw new Error(
            "TUI command must not call the OpenCode prompt client",
          );
        },
      },
    ),
  } as unknown as TuiPluginApi;

  try {
    await registerGlinerPruneCommand(api);
    await registered?.onSelect?.();
    assert.equal(clientAccesses, 0);
    assert.deepEqual(toasts, [
      {
        variant: "info",
        title: "GLiNER Prune",
        message: "Analyzing tool interactions locally…",
        duration: 2_000,
      },
      {
        variant: "success",
        title: "GLiNER Prune",
        message: "GLiNER prune ready",
      },
    ]);
  } finally {
    await stopBridge(server, socketPath, directory);
    await rm(directory, { recursive: true });
  }
});
