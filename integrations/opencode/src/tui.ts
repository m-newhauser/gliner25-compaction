import { randomUUID } from "node:crypto";
import type { TuiPluginApi, TuiPluginModule } from "@opencode-ai/plugin/tui";
import { bridgeSocketPath, callBridge } from "./bridge.js";

const PRUNE_TIMEOUT_MS = 800_000;

export async function registerGlinerPruneCommand(
  api: TuiPluginApi,
): Promise<void> {
  if (!api.command) {
    throw new Error(
      "This OpenCode version does not expose TUI command registration",
    );
  }

  const dispose = api.command.register(() => [
    {
      title: "Prune context locally",
      value: "gliner-prune.apply",
      description: "Prune old tool output while preserving exact evidence",
      category: "GLiNER",
      slash: { name: "gliner-prune" },
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
          message: "Preparing the local model and pruning context…",
          duration: 2_000,
        });
        try {
          const response = await callBridge(
            bridgeSocketPath(api.state.path.directory),
            { id: randomUUID(), method: "apply", sessionID },
            PRUNE_TIMEOUT_MS,
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
            message:
              error instanceof Error
                ? error.message
                : "GLiNER pruning failed",
          });
        }
      },
    },
  ]);
  api.lifecycle.onDispose(dispose);
}

const tui: TuiPluginModule["tui"] = async (api) => {
  await registerGlinerPruneCommand(api);
};

export default {
  id: "opencode-gliner-prune",
  tui,
} satisfies TuiPluginModule;
