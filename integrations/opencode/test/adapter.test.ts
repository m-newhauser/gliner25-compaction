import assert from "node:assert/strict";
import test from "node:test";
import {
  applyDecisions,
  deriveGoal,
  toCanonicalMessages,
  transcriptFingerprint,
  type OpenCodeMessage,
} from "../src/opencode/adapter.js";

function fixture(): OpenCodeMessage[] {
  return [
    {
      info: {
        id: "user-1",
        sessionID: "session-1",
        role: "user",
        custom: "preserved",
      },
      parts: [
        {
          id: "text-1",
          type: "text",
          text: "Fix the parser test.",
          metadata: { source: "user" },
        },
      ],
    },
    {
      info: {
        id: "assistant-1",
        sessionID: "session-1",
        role: "assistant",
      },
      parts: [
        {
          id: "reasoning-1",
          type: "reasoning",
          text: "I will inspect it.",
        },
        {
          id: "tool-1",
          type: "tool",
          callID: "call-1",
          tool: "read",
          state: {
            status: "completed",
            input: { filePath: "parser.py" },
            output: "noise expected 2 received 3 tail",
          },
          metadata: { opaque: true },
        },
        {
          id: "tool-2",
          type: "tool",
          callID: "call-2",
          tool: "read",
          state: {
            status: "completed",
            input: { filePath: "old.py" },
            output: "obsolete",
          },
        },
      ],
    },
  ];
}

test("adapter extracts only user text and completed tool interactions", () => {
  const messages = toCanonicalMessages(fixture());
  assert.equal(messages[0]?.text, "Fix the parser test.");
  assert.equal(messages[1]?.text, "");
  assert.deepEqual(messages[1]?.tool_uses, [
    {
      id: "call-1",
      name: "read",
      input: { filePath: "parser.py" },
    },
    {
      id: "call-2",
      name: "read",
      input: { filePath: "old.py" },
    },
  ]);
  assert.equal(
    messages[1]?.tool_results[0]?.text,
    "noise expected 2 received 3 tail",
  );
});

test("adapter applies exact evidence and drops only the selected tool part", () => {
  const messages = fixture();
  applyDecisions(
    messages,
    [
      {
        tool_use_id: "call-1",
        action: "keep_evidence",
        confidence: 0.95,
        reasons: ["protected_evidence"],
        evidence: [
          {
            start: 6,
            end: 27,
            text: "expected 2 received 3",
            kind: "expected_value",
            confidence: 0.9,
          },
        ],
      },
      {
        tool_use_id: "call-2",
        action: "drop",
        confidence: 0.95,
        reasons: ["superseded"],
        evidence: [],
      },
    ],
    0,
  );

  const assistant = messages[1]!;
  assert.equal(assistant.parts.length, 2);
  assert.equal(assistant.parts[0]?.type, "reasoning");
  assert.equal(assistant.parts[1]?.state?.output, "expected 2 received 3");
  assert.deepEqual(assistant.parts[1]?.metadata, { opaque: true });
});

test("goal and fingerprint include recent user intent and optional focus", () => {
  const messages = fixture();
  assert.equal(
    deriveGoal(messages, "Keep the failing assertion"),
    "Fix the parser test.\n\nKeep the failing assertion",
  );
  assert.equal(
    transcriptFingerprint(messages, ""),
    transcriptFingerprint(structuredClone(messages), ""),
  );
  assert.notEqual(
    transcriptFingerprint(messages, ""),
    transcriptFingerprint(messages, "new focus"),
  );

  const continued = [
    ...messages,
    {
      info: { id: "user-2", sessionID: "session-1", role: "user" },
      parts: [{ type: "text", text: "Continue." }],
    },
    {
      info: { id: "user-3", sessionID: "session-1", role: "user" },
      parts: [{ type: "text", text: "continue" }],
    },
  ];
  assert.equal(deriveGoal(continued), "Fix the parser test.");
});
