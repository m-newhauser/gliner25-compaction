import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  mkdir,
  readdir,
  readFile,
  rename,
  unlink,
  writeFile,
} from "node:fs/promises";
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

function bridgeLocatorPrefix(directory: string): string {
  return `${directoryDigest(directory)}-`;
}

function bridgeLocatorPath(directory: string, socketPath: string): string {
  const socketDigest = createHash("sha256")
    .update(socketPath)
    .digest("hex")
    .slice(0, 12);
  return join(
    bridgeDirectory(),
    `${bridgeLocatorPrefix(directory)}${socketDigest}.json`,
  );
}

export async function publishBridge(
  directory: string,
  socketPath: string,
): Promise<void> {
  await ensureBridgeDirectory();
  const locator = bridgeLocatorPath(directory, socketPath);
  const temporary = `${locator}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify({ socketPath }), {
    mode: 0o600,
  });
  await rename(temporary, locator);
}

export async function resolveBridgeSockets(
  directory: string,
): Promise<string[]> {
  await ensureBridgeDirectory();
  const prefix = bridgeLocatorPrefix(directory);
  const files = (await readdir(bridgeDirectory())).filter(
    (file) => file.startsWith(prefix) && file.endsWith(".json"),
  );
  const sockets = await Promise.all(
    files.map(async (file) => {
      const value = JSON.parse(
        await readFile(join(bridgeDirectory(), file), "utf8"),
      ) as { socketPath?: unknown };
      if (
        typeof value.socketPath !== "string" ||
        !value.socketPath.startsWith(`${bridgeDirectory()}/`)
      ) {
        throw new Error("invalid GLiNER prune bridge locator");
      }
      return value.socketPath;
    }),
  );
  if (sockets.length === 0) {
    throw new Error("GLiNER prune bridge is not running");
  }
  return sockets;
}

export async function resolveBridgeSocket(directory: string): Promise<string> {
  return (await resolveBridgeSockets(directory))[0]!;
}

async function unpublishBridge(
  directory: string,
  socketPath: string,
): Promise<void> {
  const locator = bridgeLocatorPath(directory, socketPath);
  try {
    await unlink(locator);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
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
  directory?: string,
): Promise<void> {
  await new Promise<void>((resolve) => server.close(() => resolve()));
  await unlink(socketPath).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== "ENOENT") throw error;
  });
  if (directory) await unpublishBridge(directory, socketPath);
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

export async function callPublishedBridge(
  directory: string,
  request: BridgeRequest,
  timeoutMs = 2_000,
): Promise<BridgeResponse> {
  let lastResponse: BridgeResponse | undefined;
  let lastError: Error | undefined;
  for (const socketPath of await resolveBridgeSockets(directory)) {
    try {
      const response = await callBridge(socketPath, request, timeoutMs);
      if (response.ok) return response;
      lastResponse = response;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  if (lastResponse) return lastResponse;
  throw lastError ?? new Error("GLiNER prune bridge is unavailable");
}
