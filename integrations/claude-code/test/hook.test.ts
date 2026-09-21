import assert from "node:assert/strict";
import test from "node:test";

import { register } from "../hooks/gliner25-pruning.ts";

type Handler = (
  engine: any,
  event: any,
  next: (event: any) => Promise<any>,
) => Promise<any>;

function registered(options: Record<string, unknown> = {}): Handler {
  let handler: Handler | undefined;
  register(
    ((name: string, value: Handler) => {
      assert.equal(name, "session.compact");
      handler = value;
    }) as never,
    options as never,
  );
  assert.ok(handler);
  return handler;
}

const event = {
  trigger: "manual",
  messages: [{ role: "user", text: "Goal", toolUses: [], handle: "h1" }],
};

test("worker timeout falls back atomically to host compaction", async () => {
  const hook = registered({ shadowMode: false });
  let nextCalls = 0;
  const result = await hook(
    {
      env: { get: async () => "/python" },
      process: { run: async () => Promise.reject(new Error("timed out")) },
      ui: { log() {}, toast() {} },
    },
    event,
    async (received) => {
      nextCalls += 1;
      assert.equal(received, event);
      return { messages: event.messages };
    },
  );
  assert.equal(nextCalls, 1);
  assert.deepEqual(result, { messages: event.messages });
});

test("unchanged fallback skips instead of invoking the host", async () => {
  const hook = registered({ shadowMode: false, fallback: "unchanged" });
  const result = await hook(
    {
      env: { get: async () => "/python" },
      process: {
        run: async () => ({ exitCode: 1, stdout: "", stderr: "failed" }),
      },
      ui: { log() {}, toast() {} },
    },
    event,
    async () => {
      throw new Error("host fallback should not run");
    },
  );
  assert.match(result.skip, /worker failed/);
});

test("shadow mode returns a manifest without replacing history", async () => {
  const logs: string[] = [];
  const hook = registered();
  const result = await hook(
    {
      env: { get: async () => "/python" },
      process: {
        run: async () => ({
          exitCode: 0,
          stderr: "",
          stdout: JSON.stringify({
            messages: event.messages,
            manifest: {
              characters_before: 100,
              characters_after: 50,
              reduction: 0.5,
              decisions: [],
            },
          }),
        }),
      },
      ui: {
        log(value: string) {
          logs.push(value);
        },
        toast() {},
      },
    },
    event,
    async () => {
      throw new Error("shadow mode should not invoke host compaction");
    },
  );
  assert.match(result.skip, /shadow mode/);
  assert.match(logs[0] ?? "", /50% reduction/);
});
