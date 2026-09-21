import {
  spawn,
  type ChildProcess,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import type { AnalyzePayload, AnalyzeResult } from "./protocol.js";

type PendingRequest = {
  resolve: (value: AnalyzeResult) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

type SidecarClientOptions = {
  checkpoint?: string;
  projectDirectory?: string;
  startupTimeoutMs?: number;
  requestTimeoutMs?: number;
  setupTimeoutMs?: number;
  onLog?: (message: string) => void;
};

const DEFAULT_CHECKPOINT = "fastino/gliner2.5-small-v1";

function defaultProjectDirectory(): string {
  const packaged = fileURLToPath(new URL("./runtime", import.meta.url));
  if (existsSync(new URL("./runtime/pyproject.toml", import.meta.url))) {
    return packaged;
  }
  return fileURLToPath(new URL("../../../", import.meta.url));
}

export class SidecarClient {
  readonly #options: Required<Omit<SidecarClientOptions, "onLog">> & {
    onLog?: (message: string) => void;
  };
  readonly #pending = new Map<string, PendingRequest>();
  #child?: ChildProcessWithoutNullStreams;
  #ready?: Promise<void>;
  #setup?: Promise<void>;
  #setupChild?: ChildProcess;
  #stopping = false;

  constructor(options: SidecarClientOptions = {}) {
    this.#options = {
      checkpoint: options.checkpoint ?? DEFAULT_CHECKPOINT,
      projectDirectory: options.projectDirectory ?? defaultProjectDirectory(),
      startupTimeoutMs: options.startupTimeoutMs ?? 90_000,
      requestTimeoutMs: options.requestTimeoutMs ?? 90_000,
      setupTimeoutMs: options.setupTimeoutMs ?? 600_000,
      onLog: options.onLog,
    };
  }

  get running(): boolean {
    return this.#child !== undefined && this.#child.exitCode === null;
  }

  async setup(): Promise<void> {
    if (this.#stopping) throw new Error("GLiNER prune sidecar stopped");
    if (this.#setup) return await this.#setup;
    this.#setup = this.#runSetup();
    try {
      await this.#setup;
    } finally {
      this.#setup = undefined;
    }
  }

  async #runSetup(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(
        "uv",
        [
          "run",
          "--no-dev",
          "--project",
          this.#options.projectDirectory,
          "python",
          join(this.#options.projectDirectory, "scripts", "download_model.py"),
        ],
        {
          stdio: ["ignore", "pipe", "pipe"],
          env: {
            ...process.env,
            GLINER25_CHECKPOINT: this.#options.checkpoint,
          },
        },
      );
      this.#setupChild = child;
      let errorOutput = "";
      let settled = false;
      let terminationError: Error | undefined;
      let forceKill: NodeJS.Timeout | undefined;
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (forceKill) clearTimeout(forceKill);
        if (this.#setupChild === child) this.#setupChild = undefined;
        if (error) reject(error);
        else resolve();
      };
      const timer = setTimeout(() => {
        terminationError = new Error("GLiNER prune setup timed out");
        child.kill();
        forceKill = setTimeout(() => child.kill("SIGKILL"), 1_000);
      }, this.#options.setupTimeoutMs);
      child.stderr.setEncoding("utf8");
      child.stderr.on("data", (chunk) => {
        errorOutput += String(chunk);
      });
      child.once("error", (error) => finish(error));
      child.once("exit", (code) => {
        if (terminationError) finish(terminationError);
        else if (code === 0) finish();
        else
          finish(
            new Error(
              errorOutput.trim() ||
                `GLiNER prune setup exited with status ${code ?? "unknown"}`,
            ),
          );
      });
    });
    await this.start();
  }

  async start(): Promise<void> {
    if (this.#stopping) throw new Error("GLiNER prune sidecar stopped");
    if (this.#ready) return await this.#ready;
    if (!existsSync(join(this.#options.projectDirectory, ".venv"))) {
      throw new Error("Run /gliner-prune-setup before pruning");
    }
    this.#ready = this.#start();
    try {
      await this.#ready;
    } catch (error) {
      this.#ready = undefined;
      throw error;
    }
  }

  async analyze(payload: AnalyzePayload): Promise<AnalyzeResult> {
    await this.start();
    if (this.#stopping) throw new Error("GLiNER prune sidecar stopped");
    const child = this.#child;
    if (!child) throw new Error("GLiNER prune sidecar is not running");
    const id = randomUUID();
    return await new Promise<AnalyzeResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        const error = new Error("GLiNER prune analysis timed out");
        reject(error);
        this.#terminateChild(child, error);
      }, this.#options.requestTimeoutMs);
      this.#pending.set(id, { resolve, reject, timer });
      const request = `${JSON.stringify({
        v: 1,
        type: "request",
        id,
        method: "analyze",
        payload,
      })}\n`;
      const failWrite = (error: Error) => {
        const pending = this.#pending.get(id);
        if (!pending) return;
        this.#pending.delete(id);
        clearTimeout(pending.timer);
        pending.reject(error);
      };
      try {
        child.stdin.write(request, (error) => {
          if (error) failWrite(error);
        });
      } catch (error) {
        failWrite(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }

  #terminateChild(child: ChildProcessWithoutNullStreams, error: Error): void {
    if (this.#child === child) {
      this.#child = undefined;
      this.#ready = undefined;
    }
    this.#failAll(error);
    child.kill();
    const forceKill = setTimeout(() => {
      if (child.exitCode === null) child.kill("SIGKILL");
    }, 1_000);
    forceKill.unref();
    child.once("exit", () => clearTimeout(forceKill));
  }

  async stop(): Promise<void> {
    this.#stopping = true;
    const setupChild = this.#setupChild;
    if (setupChild && setupChild.exitCode === null) {
      await new Promise<void>((resolve) => {
        const forceKill = setTimeout(() => setupChild.kill("SIGKILL"), 1_000);
        const giveUp = setTimeout(resolve, 2_000);
        setupChild.once("exit", () => {
          clearTimeout(forceKill);
          clearTimeout(giveUp);
          resolve();
        });
        setupChild.kill();
      });
    }
    this.#setupChild = undefined;
    const child = this.#child;
    this.#ready = undefined;
    if (!child || child.exitCode !== null) return;
    this.#failAll(new Error("GLiNER prune sidecar stopped"));
    try {
      child.stdin.write(
        `${JSON.stringify({
          v: 1,
          type: "request",
          id: randomUUID(),
          method: "shutdown",
          payload: {},
        })}\n`,
        (error) => {
          if (error) child.kill();
        },
      );
    } catch {
      child.kill();
    }
    await new Promise<void>((resolve) => {
      const forceKill = setTimeout(() => child.kill("SIGKILL"), 1_000);
      const giveUp = setTimeout(resolve, 2_000);
      child.once("exit", () => {
        clearTimeout(forceKill);
        clearTimeout(giveUp);
        resolve();
      });
    });
    if (this.#child === child) this.#child = undefined;
  }

  async #start(): Promise<void> {
    const child = spawn(
      "uv",
      [
        "run",
        "--no-dev",
        "--project",
        this.#options.projectDirectory,
        "python",
        "-m",
        "gliner25_context_compaction.sidecar",
        "--checkpoint",
        this.#options.checkpoint,
      ],
      {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          HF_HUB_OFFLINE: "1",
          TRANSFORMERS_OFFLINE: "1",
          UV_OFFLINE: "1",
        },
      },
    );
    this.#child = child;
    child.stdin.on("error", (error) => this.#failAll(error));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      const message = String(chunk).trim();
      if (message) this.#options.onLog?.(message);
    });
    child.once("exit", (code, signal) => {
      if (this.#child !== child) return;
      this.#child = undefined;
      this.#ready = undefined;
      const error = new Error(
        `GLiNER prune sidecar exited (${signal ?? code ?? "unknown"})`,
      );
      for (const pending of this.#pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(error);
      }
      this.#pending.clear();
    });

    const lines = createInterface({ input: child.stdout });
    const ready = new Promise<void>((resolve, reject) => {
      let settled = false;
      let timer: NodeJS.Timeout;
      const cleanup = () => {
        clearTimeout(timer);
        lines.off("line", onReady);
        child.off("error", onError);
        child.off("exit", onExit);
      };
      const fail = (error: Error) => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(error);
      };
      const onError = (error: Error) => fail(error);
      const onExit = (code: number | null, signal: NodeJS.Signals | null) =>
        fail(
          new Error(
            `GLiNER prune sidecar exited before ready (${signal ?? code ?? "unknown"})`,
          ),
        );
      const onReady = (line: string) => {
        try {
          const message = JSON.parse(line) as {
            type?: string;
            v?: number;
          };
          if (message.type !== "ready" || message.v !== 1) {
            throw new Error("invalid sidecar ready message");
          }
          if (settled) return;
          settled = true;
          cleanup();
          resolve();
        } catch (error) {
          child.kill();
          fail(error instanceof Error ? error : new Error(String(error)));
        }
      };
      lines.on("line", onReady);
      child.once("error", onError);
      child.once("exit", onExit);
      timer = setTimeout(() => {
        child.kill();
        fail(new Error("GLiNER prune sidecar startup timed out"));
      }, this.#options.startupTimeoutMs);
    });
    await ready;

    lines.on("line", (line) => {
      let message: {
        id?: string;
        ok?: boolean;
        result?: AnalyzeResult;
        error?: string;
      };
      try {
        message = JSON.parse(line);
      } catch {
        this.#failAll(new Error("sidecar returned malformed JSON"));
        return;
      }
      if (!message.id) return;
      const pending = this.#pending.get(message.id);
      if (!pending) return;
      this.#pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.ok && message.result) pending.resolve(message.result);
      else
        pending.reject(new Error(message.error ?? "sidecar analysis failed"));
    });
  }

  #failAll(error: Error): void {
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
  }
}
