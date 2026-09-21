declare module "claude-code" {
  export type PluginOptions = Readonly<
    Record<string, string | number | boolean | readonly string[]>
  >;

  export type ToolUseSummary = {
    tool_use_id: string;
    tool: string;
    input: Record<string, unknown>;
    text?: string;
    isError?: boolean;
    [key: string]: unknown;
  };

  export type ToolResultSummary = {
    tool_use_id: string;
    text: string;
    isError?: boolean;
    [key: string]: unknown;
  };

  export type SessionMessage = {
    role: "user" | "assistant";
    text: string;
    toolUses: ToolUseSummary[];
    toolResults?: ToolResultSummary[];
    handle?: string;
    [key: string]: unknown;
  };

  export type SessionCompactInput = {
    trigger: "manual" | "auto" | "plugin" | "precompute";
    agentId?: string;
    instructions?: string;
    messages: readonly SessionMessage[];
  };

  export type SessionCompactResult =
    | { messages: readonly SessionMessage[]; skip?: undefined }
    | { skip: string; messages?: undefined };

  export type Engine = {
    env: { get(name: string): Promise<string | undefined> };
    process: {
      run(
        argv: readonly string[],
        options?: { stdin?: string; timeoutMs?: number },
      ): Promise<{ exitCode: number; stdout: string; stderr: string }>;
    };
    ui: {
      log(text: string): void;
      toast(text: string, options?: { timeoutMs?: number }): void;
    };
  };

  export type Next = (
    event: SessionCompactInput,
  ) => Promise<SessionCompactResult>;

  export type On = (
    name: "session.compact",
    handler: (
      engine: Engine,
      event: SessionCompactInput,
      next: Next,
    ) => Promise<SessionCompactResult>,
  ) => void;

  export type Register = (on: On, options: PluginOptions) => unknown;
}
