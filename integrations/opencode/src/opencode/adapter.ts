import { createHash } from "node:crypto";
import type {
  CanonicalMessage,
  EvidenceSpan,
  RetentionDecision,
} from "../protocol.js";

export type OpenCodePart = {
  type: string;
  text?: string;
  ignored?: boolean;
  callID?: string;
  tool?: string;
  state?: {
    status?: string;
    input?: Record<string, unknown>;
    output?: string;
    error?: string;
  };
  [key: string]: unknown;
};

export type OpenCodeMessage = {
  info: {
    id: string;
    sessionID: string;
    role: string;
    [key: string]: unknown;
  };
  parts: OpenCodePart[];
};

function toolResultText(part: OpenCodePart): string | undefined {
  if (part.state?.status === "completed") return part.state.output ?? "";
  if (part.state?.status === "error") return part.state.error ?? "";
  return undefined;
}

export function isContinuationText(text: string): boolean {
  return /^continue[.! ]*$/i.test(text.trim());
}

export function toCanonicalMessages(
  messages: OpenCodeMessage[],
): CanonicalMessage[] {
  return messages.map((message) => {
    const toolParts = message.parts.filter(
      (part) =>
        part.type === "tool" &&
        typeof part.callID === "string" &&
        typeof part.tool === "string",
    );
    return {
      role: message.info.role,
      text: message.parts
        .filter(
          (part) =>
            part.type === "text" &&
            part.ignored !== true &&
            typeof part.text === "string",
        )
        .map((part) => part.text)
        .join("\n"),
      tool_uses: toolParts.map((part) => ({
        id: part.callID!,
        name: part.tool!,
        input: part.state?.input ?? {},
      })),
      tool_results: toolParts.flatMap((part) => {
        const text = toolResultText(part);
        if (text === undefined) return [];
        return [
          {
            tool_use_id: part.callID!,
            text,
            is_error: part.state?.status === "error",
          },
        ];
      }),
    };
  });
}

function mergeRanges(
  spans: EvidenceSpan[],
  textLength: number,
  contextCharacters: number,
): Array<[number, number]> {
  const ranges = spans
    .map((span): [number, number] => [
      Math.max(0, span.start - contextCharacters),
      Math.min(textLength, span.end + contextCharacters),
    ])
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  const merged: Array<[number, number]> = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1]) {
      previous[1] = Math.max(previous[1], range[1]);
    } else {
      merged.push(range);
    }
  }
  return merged;
}

function evidenceText(
  text: string,
  spans: EvidenceSpan[],
  contextCharacters: number,
): string {
  for (const span of spans) {
    if (
      span.start < 0 ||
      span.end < span.start ||
      span.end > text.length ||
      text.slice(span.start, span.end) !== span.text
    ) {
      throw new Error("GLiNER returned an invalid evidence span");
    }
  }
  return mergeRanges(spans, text.length, contextCharacters)
    .map(([start, end]) => text.slice(start, end))
    .join("\n[... omitted ...]\n");
}

export function applyDecisions(
  messages: OpenCodeMessage[],
  decisions: RetentionDecision[],
  contextCharacters: number,
): void {
  const byID = new Map(
    decisions.map((decision) => [decision.tool_use_id, decision]),
  );
  for (const message of messages) {
    message.parts = message.parts.filter((part) => {
      if (part.type !== "tool" || !part.callID) return true;
      const decision = byID.get(part.callID);
      if (!decision || decision.action === "keep_full") return true;
      if (decision.action === "drop") return false;

      const source = toolResultText(part);
      if (source === undefined) return true;
      const replacement =
        decision.action === "keep_call_only"
          ? "[tool result omitted; re-run if needed]"
          : evidenceText(source, decision.evidence, contextCharacters);
      if (part.state?.status === "completed") part.state.output = replacement;
      if (part.state?.status === "error") part.state.error = replacement;
      return true;
    });
  }
}

export function transcriptFingerprint(
  messages: OpenCodeMessage[],
  focus: string,
): string {
  return createHash("sha256")
    .update(JSON.stringify({ messages: toCanonicalMessages(messages), focus }))
    .digest("hex");
}

export function deriveGoal(messages: OpenCodeMessage[], focus = ""): string {
  const recentUserText = messages
    .filter((message) => message.info.role === "user")
    .flatMap((message) =>
      message.parts
        .filter(
          (part) =>
            part.type === "text" &&
            part.ignored !== true &&
            typeof part.text === "string",
        )
        .map((part) => part.text!.trim())
        .filter(Boolean),
    )
    .filter((text) => !isContinuationText(text))
    .slice(-3)
    .join("\n");
  return [recentUserText, focus.trim()].filter(Boolean).join("\n\n");
}
