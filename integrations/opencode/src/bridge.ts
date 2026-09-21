import { createHash } from "node:crypto";
import { chmod, mkdir, unlink } from "node:fs/promises";
import { createConnection, createServer, type Server } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

const MAX_MESSAGE_BYTES = 64 * 1024;

export type BridgeRequest = {
  id: string;
  method: "setup" | "preview" | "apply" | "status" | "reset";
  sessionID?: string;
  focus?: string;
};

export type BridgeResponse =
  | { id: string; ok: true; result: { message: string } }
  | { id: string; ok: false; error: string };

function bridgeDirectory(): string {
  const user = typeof process.getuid === "function" ? process.getuid() : "user";
  const root = process.platform === "darwin" ? "/tmp" : tmpdir();
  return join(root, `gliner-prune-${user}`);
}

function directoryDigest(directory: string): string {
  return createHash("sha256").update(directory).digest("hex").slice(0, 16);
}

async function ensureBridgeDirectory(): Promise<void> {
  const path = bridgeDirectory();
  await mkdir(path, { recursive: true, mode: 0o700 });
  await chmod(path, 0o700);
}

export function bridgeSocketPath(
  directory: string,
  instance = String(process.pid),
): string {
  const safeInstance = instance.replaceAll(/[^a-zA-Z0-9_-]/g, "").slice(0, 12);
  return join(
    bridgeDirectory(),
    `${directoryDigest(directory)}-${safeInstance}.sock`,
  );
}

export async function startBridge(
  socketPath: string,
  handle: (request: BridgeRequest) => Promise<BridgeResponse>,
): Promise<Server> {
  await ensureBridgeDirectory();
  await unlink(socketPath).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== "ENOENT") throw error;
  });

  const server = createServer((socket) => {
    let data = "";
    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      data += chunk;
      if (Buffer.byteLength(data) > MAX_MESSAGE_BYTES) {
        socket.destroy(new Error("bridge request exceeds size limit"));
        return;
      }
      const newline = data.indexOf("\n");
      if (newline < 0) return;

      const line = data.slice(0, newline);
      data = "";
      void (async () => {
        try {
          const request = JSON.parse(line) as BridgeRequest;
          const response = await handle(request);
          socket.end(`${JSON.stringify(response)}\n`);
        } catch (error) {
          const message =
            error instanceof Error ? error.message : String(error);
          socket.end(
            `${JSON.stringify({ id: "", ok: false, error: message })}\n`,
          );
        }
      })();
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, () => {
      server.off("error", reject);
      resolve();
    });
  });
  await chmod(socketPath, 0o600);
  return server;
}

export async function stopBridge(
  server: Server,
  socketPath: string,
): Promise<void> {
  await new Promise<void>((resolve) => server.close(() => resolve()));
  await unlink(socketPath).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== "ENOENT") throw error;
  });
}

export async function callBridge(
  socketPath: string,
  request: BridgeRequest,
  timeoutMs = 2_000,
): Promise<BridgeResponse> {
  return await new Promise<BridgeResponse>((resolve, reject) => {
    const socket = createConnection(socketPath);
    let data = "";
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("GLiNER prune bridge timed out"));
    }, timeoutMs);

    const finish = (callback: () => void) => {
      clearTimeout(timer);
      callback();
    };

    socket.setEncoding("utf8");
    socket.once("error", (error) => finish(() => reject(error)));
    socket.on("data", (chunk) => {
      data += chunk;
      if (Buffer.byteLength(data) > MAX_MESSAGE_BYTES) {
        socket.destroy();
        finish(() => reject(new Error("bridge response exceeds size limit")));
        return;
      }
      const newline = data.indexOf("\n");
      if (newline < 0) return;
      socket.end();
      finish(() =>
        resolve(JSON.parse(data.slice(0, newline)) as BridgeResponse),
      );
    });
    socket.once("connect", () => socket.write(`${JSON.stringify(request)}\n`));
  });
}
