import type { Hooks, Plugin } from "@opencode-ai/plugin";
import { bridgeSocketPath, startBridge, stopBridge } from "./bridge.js";
import {
  applyDecisions,
  deriveGoal,
  isContinuationText,
  toCanonicalMessages,
  transcriptFingerprint,
  type OpenCodeMessage,
} from "./opencode/adapter.js";
import type { AnalyzeResult } from "./protocol.js";
import { SidecarClient } from "./sidecar-client.js";

export type PruneSidecar = Pick<
  SidecarClient,
  "running" | "setup" | "analyze" | "stop"
>;

type PreviewState = {
  fingerprint: string;
  focus: string;
  result: AnalyzeResult;
};

type ActiveState = {
  result: AnalyzeResult;
  lastUserMessageID?: string;
};

export type SessionPruneState = {
  preview?: PreviewState;
  active?: ActiveState;
};

function latestUserMessage(messages: OpenCodeMessage[]) {
  return messages.findLast((message) => message.info.role === "user");
}

function isContinuation(message: OpenCodeMessage): boolean {
  const text = message.parts
    .filter(
      (part) =>
        part.type === "text" &&
        part.ignored !== true &&
        typeof part.text === "string",
    )
    .map((part) => part.text)
    .join(" ")
    .trim();
  return isContinuationText(text);
}

export function createMessageTransform(
  sessions: Map<string, SessionPruneState>,
  onError: (error: Error) => void = () => {},
): NonNullable<Hooks["experimental.chat.messages.transform"]> {
  return async (_input, output) => {
    const sessionID = output.messages.find(
      (message) => typeof message.info.sessionID === "string",
    )?.info.sessionID;
    if (!sessionID) return;
    const session = sessions.get(sessionID);
    const active = session?.active;
    if (!active) return;
    const messages = output.messages as unknown as OpenCodeMessage[];
    const latestUser = latestUserMessage(messages);
    if (
      latestUser &&
      active.lastUserMessageID &&
      latestUser.info.id !== active.lastUserMessageID
    ) {
      if (!isContinuation(latestUser)) {
        session.active = undefined;
        return;
      }
      active.lastUserMessageID = latestUser.info.id;
    }
    try {
      const transformed = structuredClone(messages);
      applyDecisions(
        transformed,
        active.result.decisions,
        active.result.context_characters,
      );
      output.messages = transformed as unknown as typeof output.messages;
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  };
}

export function createOpenCodeGlinerPrunePlugin(
  sidecarFactory: (onLog: (message: string) => void) => PruneSidecar = (
    onLog,
  ) => new SidecarClient({ onLog }),
): Plugin {
  return async ({ client, directory }) => {
    const sessions = new Map<string, SessionPruneState>();
    const sidecar = sidecarFactory((message) => {
      void client.app.log({
        body: {
          service: "opencode-gliner-prune",
          level: "debug",
          message,
        },
      });
    });
    const modelReady = sidecar.setup();
    void modelReady.catch((error) => {
      void client.app.log({
        body: {
          service: "opencode-gliner-prune",
          level: "error",
          message: "GLiNER model failed to load",
          extra: {
            error: error instanceof Error ? error.message : String(error),
          },
        },
      });
    });

    const sessionMessages = async (sessionID: string) => {
      const response = await client.session.messages({
        path: { id: sessionID },
      });
      return (response.data ?? response) as unknown as OpenCodeMessage[];
    };

    const analyze = async (sessionID: string, focus: string) => {
      await modelReady;
      const messages = await sessionMessages(sessionID);
      const goal =
        deriveGoal(messages, focus) || "Continue the current coding task.";
      const result = await sidecar.analyze({
        messages: toCanonicalMessages(messages),
        goal,
      });
      return {
        messages,
        result,
        fingerprint: transcriptFingerprint(messages, focus),
      };
    };

    const summary = (result: AnalyzeResult, verb: string) => {
      const changed = result.decisions.filter(
        (decision) => decision.action !== "keep_full",
      ).length;
      const actionCounts = {
        drop: result.decisions.filter((decision) => decision.action === "drop")
          .length,
        reduce: result.decisions.filter(
          (decision) => decision.action === "keep_evidence",
        ).length,
        omit: result.decisions.filter(
          (decision) => decision.action === "keep_call_only",
        ).length,
        full: result.decisions.filter(
          (decision) => decision.action === "keep_full",
        ).length,
      };
      const beforeTokens = Math.ceil(result.characters_before / 4);
      const afterTokens = Math.ceil(result.characters_after / 4);
      const excerpts = result.decisions
        .flatMap((decision) => decision.evidence.map((span) => span.text))
        .filter((text, index, values) => values.indexOf(text) === index)
        .slice(0, 3)
        .map((text) => `"${text.replaceAll("\n", " ").slice(0, 60)}"`);
      const reduction = (result.reduction * 100).toFixed(1);
      return [
        `${verb} by ${reduction}%`,
        `${changed}/${result.decisions.length} tool results changed · ~${beforeTokens.toLocaleString()} → ~${afterTokens.toLocaleString()} estimated tokens`,
        `Dropped ${actionCounts.drop} · reduced ${actionCounts.reduce} · omitted ${actionCounts.omit} · kept ${actionCounts.full} full`,
        excerpts.length ? `Preserved: ${excerpts.join(", ")}` : "",
        result.warnings.length
          ? `Warnings: ${result.warnings.slice(0, 2).join("; ")}`
          : "",
        "Stored history unchanged; a new substantive prompt restores full context",
      ]
        .filter(Boolean)
        .join("\n");
    };

    const socketPath = bridgeSocketPath(directory);
    const bridge = await startBridge(socketPath, async (request) => {
      try {
        if (request.method === "setup") {
          await modelReady;
          return {
            id: request.id,
            ok: true,
            result: { message: "GLiNER small checkpoint is ready locally" },
          };
        }
        if (request.sessionID) {
          const ownership = (await client.session.get({
            path: { id: request.sessionID },
          })) as { data?: unknown; error?: unknown };
          if (ownership.error || !ownership.data) {
            throw new Error("OpenCode session is not owned by this process");
          }
        }
        if (request.method === "status") {
          const active = request.sessionID
            ? sessions.get(request.sessionID)?.active
            : undefined;
          return {
            id: request.id,
            ok: true,
            result: {
              message: active
                ? `${summary(active.result, "Active:")}; history unchanged`
                : `GLiNER prune ${sidecar.running ? "ready" : "not loaded"}; no active pruning`,
            },
          };
        }
        if (!request.sessionID) {
          throw new Error("OpenCode session is required");
        }
        const session = sessions.get(request.sessionID) ?? {};
        if (request.method === "reset") {
          sessions.delete(request.sessionID);
          return {
            id: request.id,
            ok: true,
            result: { message: "GLiNER pruning reset; full context restored" },
          };
        }
        const focus = request.focus?.trim() ?? "";
        if (request.method === "preview") {
          const analyzed = await analyze(request.sessionID, focus);
          session.preview = {
            fingerprint: analyzed.fingerprint,
            focus,
            result: analyzed.result,
          };
          sessions.set(request.sessionID, session);
          return {
            id: request.id,
            ok: true,
            result: { message: summary(analyzed.result, "Preview:") },
          };
        }
        if (request.method === "apply") {
          const messages = await sessionMessages(request.sessionID);
          const fingerprint = transcriptFingerprint(messages, focus);
          let result: AnalyzeResult;
          if (
            session.preview?.fingerprint === fingerprint &&
            session.preview.focus === focus
          ) {
            result = session.preview.result;
          } else {
            result = (await analyze(request.sessionID, focus)).result;
          }
          session.active = {
            result,
            lastUserMessageID: latestUserMessage(messages)?.info.id,
          };
          sessions.set(request.sessionID, session);
          return {
            id: request.id,
            ok: true,
            result: {
              message: summary(result, "Context pruned"),
            },
          };
        }
        throw new Error("unknown bridge method");
      } catch (error) {
        return {
          id: request.id,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    });
    await client.app.log({
      body: {
        service: "opencode-gliner-prune",
        level: "info",
        message: "GLiNER prune bridge ready",
      },
    });

    return {
      "experimental.chat.messages.transform": createMessageTransform(
        sessions,
        (error) => {
          void client.app.log({
            body: {
              service: "opencode-gliner-prune",
              level: "error",
              message: "Pruning transform failed; using full context",
              extra: { error: error.message },
            },
          });
        },
      ),
      event: async ({ event }) => {
        if (event.type !== "session.compacted") return;
        const sessionID = (event.properties as { sessionID?: string })
          .sessionID;
        if (sessionID) sessions.delete(sessionID);
      },
      dispose: async () => {
        sessions.clear();
        await sidecar.stop();
        await stopBridge(bridge, socketPath);
      },
    };
  };
}

export const OpenCodeGlinerPrunePlugin = createOpenCodeGlinerPrunePlugin();

export default {
  id: "opencode-gliner-prune",
  server: OpenCodeGlinerPrunePlugin,
};
