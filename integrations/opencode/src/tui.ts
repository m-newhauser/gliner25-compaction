import { randomUUID } from "node:crypto";
import type { TuiPluginApi, TuiPluginModule } from "@opencode-ai/plugin/tui";
import { callPublishedBridge } from "./bridge.js";

export async function registerGlinerPruneCommand(
  api: TuiPluginApi,
): Promise<void> {
  if (!api.command) {
    throw new Error(
      "This OpenCode version does not expose TUI command registration",
    );
  }

  const commands = [
    {
      method: "apply" as const,
      title: "GLiNER Prune: Apply",
      slash: "gliner-prune",
      description: "Apply local context pruning",
    },
    {
      method: "preview" as const,
      title: "GLiNER Prune: Preview",
      slash: "gliner-prune-preview",
      description: "Preview local context pruning",
    },
    {
      method: "status" as const,
      title: "GLiNER Prune: Status",
      slash: "gliner-prune-status",
      description: "Show local context-pruning status",
    },
    {
      method: "reset" as const,
      title: "GLiNER Prune: Reset",
      slash: "gliner-prune-reset",
      description: "Restore full context",
    },
    {
      method: "setup" as const,
      title: "GLiNER Prune: Setup",
      slash: "gliner-prune-setup",
      description: "Download and verify the local small checkpoint",
    },
  ];

  const dispose = api.command.register(() =>
    commands.map((command) => ({
      title: command.title,
      value: `gliner-prune.${command.method}`,
      description: command.description,
      category: "GLiNER",
      slash: { name: command.slash },
      onSelect: async () => {
        const route = api.route.current;
        const sessionID =
          route.name === "session" &&
          "params" in route &&
          typeof route.params?.sessionID === "string"
            ? route.params.sessionID
            : undefined;
        api.ui.toast({
          variant: "info",
          title: "GLiNER Prune",
          message:
            command.method === "setup"
              ? "Preparing the local model…"
              : command.method === "preview" || command.method === "apply"
                ? "Analyzing tool interactions locally…"
                : "Working…",
          duration: 2_000,
        });
        try {
          const response = await callPublishedBridge(
            api.state.path.directory,
            { id: randomUUID(), method: command.method, sessionID },
            command.method === "setup" ? 610_000 : 120_000,
          );
          api.ui.toast({
            variant: response.ok ? "success" : "error",
            title: "GLiNER Prune",
            message: response.ok ? response.result.message : response.error,
          });
        } catch (error) {
          api.ui.toast({
            variant: "error",
            title: "GLiNER Prune",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    })),
  );
  api.lifecycle.onDispose(dispose);
}

const tui: TuiPluginModule["tui"] = async (api) => {
  await registerGlinerPruneCommand(api);
};

export default {
  id: "opencode-gliner-prune",
  tui,
} satisfies TuiPluginModule;
