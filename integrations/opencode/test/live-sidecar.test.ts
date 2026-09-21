import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { SidecarClient } from "../src/sidecar-client.js";

test(
  "live sidecar analyzes locally within the V1 latency ceiling",
  { skip: process.env.GLINER25_LIVE !== "1" },
  async () => {
    const client = new SidecarClient({
      projectDirectory: fileURLToPath(new URL("../../../", import.meta.url)),
      startupTimeoutMs: 15_000,
      requestTimeoutMs: 15_000,
    });
    const started = performance.now();
    try {
      const result = await client.analyze({
        messages: [
          {
            role: "user",
            text: "Fix the parser test.",
            tool_uses: [],
            tool_results: [],
          },
          {
            role: "assistant",
            text: "",
            tool_uses: [
              {
                id: "call-1",
                name: "read",
                input: { filePath: "old.py" },
              },
            ],
            tool_results: [
              {
                tool_use_id: "call-1",
                text: "obsolete parser contents",
                is_error: false,
              },
            ],
          },
          {
            role: "user",
            text: "Continue.",
            tool_uses: [],
            tool_results: [],
          },
        ],
        goal: "Fix the parser test",
        options: { preserve_recent: 0 },
      });
      assert.equal(result.decisions.length, 1);
      assert.ok(performance.now() - started < 15_000);
    } finally {
      await client.stop();
    }
  },
);
