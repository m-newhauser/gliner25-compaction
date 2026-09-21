import assert from "node:assert/strict";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { SidecarClient } from "../src/sidecar-client.js";

test("sidecar refuses to install dependencies implicitly", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-unset-"));
  try {
    const client = new SidecarClient({ projectDirectory: directory });
    await assert.rejects(
      client.start(),
      /Run \/gliner-prune-setup before pruning/,
    );
  } finally {
    await rm(directory, { recursive: true });
  }
});

test("sidecar rejects an early exit and can start again", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-crash-"));
  const bin = join(directory, "bin");
  const count = join(directory, "count");
  await mkdir(join(directory, ".venv"), { recursive: true });
  await mkdir(bin);
  await writeFile(
    join(bin, "uv"),
    `#!/bin/sh\nprintf x >> ${JSON.stringify(count)}\nexit 7\n`,
  );
  await chmod(join(bin, "uv"), 0o700);
  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  try {
    const client = new SidecarClient({
      projectDirectory: directory,
      startupTimeoutMs: 1_000,
    });
    await assert.rejects(client.start(), /exited before ready/);
    await assert.rejects(client.start(), /exited before ready/);
    assert.equal(await readFile(count, "utf8"), "xx");
  } finally {
    process.env.PATH = originalPath;
    await rm(directory, { recursive: true });
  }
});

test("sidecar can restart after a post-ready crash", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-restart-"));
  const bin = join(directory, "bin");
  const marker = join(directory, "started");
  await mkdir(join(directory, ".venv"), { recursive: true });
  await mkdir(bin);
  await writeFile(
    join(bin, "uv"),
    `#!/bin/sh
if [ ! -f ${JSON.stringify(marker)} ]; then
  touch ${JSON.stringify(marker)}
  printf '{"v":1,"type":"ready"}\\n'
  sleep 0.05
  exit 9
fi
printf '{"v":1,"type":"ready"}\\n'
read line
exit 0
`,
  );
  await chmod(join(bin, "uv"), 0o700);
  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  const client = new SidecarClient({
    projectDirectory: directory,
    startupTimeoutMs: 1_000,
  });
  try {
    await client.start();
    await new Promise((resolve) => setTimeout(resolve, 100));
    assert.equal(client.running, false);
    await client.start();
    assert.equal(client.running, true);
  } finally {
    await client.stop();
    process.env.PATH = originalPath;
    await rm(directory, { recursive: true });
  }
});

test("stopping the sidecar rejects pending analysis immediately", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-stop-"));
  const bin = join(directory, "bin");
  await mkdir(join(directory, ".venv"), { recursive: true });
  await mkdir(bin);
  await writeFile(
    join(bin, "uv"),
    `#!/bin/sh
printf '{"v":1,"type":"ready"}\\n'
read line
exec sleep 10
`,
  );
  await chmod(join(bin, "uv"), 0o700);
  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  const client = new SidecarClient({
    projectDirectory: directory,
    startupTimeoutMs: 1_000,
    requestTimeoutMs: 10_000,
  });
  try {
    const pending = client.analyze({
      messages: [],
      goal: "test",
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    const stopped = client.stop();
    await assert.rejects(pending, /sidecar stopped/);
    await stopped;
  } finally {
    process.env.PATH = originalPath;
    await rm(directory, { recursive: true });
  }
});

test("analysis timeout terminates the busy sidecar", async () => {
  const directory = await mkdtemp(join(tmpdir(), "gliner-prune-timeout-"));
  const bin = join(directory, "bin");
  await mkdir(join(directory, ".venv"), { recursive: true });
  await mkdir(bin);
  await writeFile(
    join(bin, "uv"),
    `#!/bin/sh
printf '{"v":1,"type":"ready"}\\n'
read line
exec sleep 10
`,
  );
  await chmod(join(bin, "uv"), 0o700);
  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  const client = new SidecarClient({
    projectDirectory: directory,
    startupTimeoutMs: 1_000,
    requestTimeoutMs: 25,
  });
  try {
    await assert.rejects(
      client.analyze({ messages: [], goal: "test" }),
      /analysis timed out/,
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(client.running, false);
  } finally {
    await client.stop();
    process.env.PATH = originalPath;
    await rm(directory, { recursive: true });
  }
});
