import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repository = dirname(dirname(fileURLToPath(import.meta.url)));
const gate = join(repository, ".tmp", "opencode-release-gate");
const artifacts = join(gate, "artifacts");
const install = join(gate, "install");
const workspace = join(gate, "unrelated-project");
const sessionID = "ses_release_gate";

await rm(gate, { recursive: true, force: true });
await mkdir(artifacts, { recursive: true });
await mkdir(workspace, { recursive: true });

execFileSync(
  "npm",
  ["pack", "-w", "opencode-gliner-prune", "--pack-destination", artifacts],
  { cwd: repository, stdio: "inherit" },
);
const tarball = (await readdir(artifacts)).find((name) => name.endsWith(".tgz"));
assert.ok(tarball, "npm pack did not produce a tarball");
execFileSync(
  "npm",
  [
    "install",
    "--prefix",
    install,
    join(artifacts, tarball),
    "--ignore-scripts",
  ],
  { cwd: workspace, stdio: "inherit" },
);

const packageRoot = join(
  install,
  "node_modules",
  "opencode-gliner-prune",
);
const serverModule = await import(
  pathToFileURL(join(packageRoot, "dist", "server.js")).href
);
const tuiModule = await import(
  pathToFileURL(join(packageRoot, "dist", "tui.js")).href
);

const failure = [
  ...Array.from(
    { length: 900 },
    (_, index) =>
      `2026-09-18T10:${String(index % 60).padStart(2, "0")}:00Z DEBUG ` +
      `checkout request=${String(index).padStart(4, "0")} route=/line-items ` +
      "status=200 duration_ms=12 cache=hit",
  ),
  "FAIL tests/parser.test.mjs",
  "Expected quantity: 1200",
  "Received quantity: 120",
  "at tests/parser.test.mjs:6:10",
].join("\n");
const trace = Array.from(
  { length: 700 },
  (_, index) =>
    `trace=${String(index).padStart(4, "0")} component=checkout-parser ` +
    "event=parse result=accepted retry=false region=local",
).join("\n");
const legacy =
  "// Legacy compatibility fixture. Do not modify.\n" +
  "export const legacyParser = (raw) => raw;";

const tool = (id, filePath, output) => ({
  id: `part_${id}`,
  sessionID,
  messageID: "msg_tools",
  type: "tool",
  callID: id,
  tool: "read",
  state: {
    status: "completed",
    input: { filePath },
    output,
    title: `Read ${filePath}`,
    metadata: {},
    time: { start: 1, end: 2 },
  },
});
const messages = [
  {
    info: { id: "msg_goal", sessionID, role: "user" },
    parts: [
      {
        id: "part_goal",
        sessionID,
        messageID: "msg_goal",
        type: "text",
        text: "Diagnose the quantity failure and preserve src/legacy/.",
      },
    ],
  },
  {
    info: { id: "msg_tools", sessionID, role: "assistant" },
    parts: [
      tool("failure_1", "logs/failure.log", failure),
      tool("failure_2", "logs/failure.log", failure),
      tool("trace_1", "logs/request-trace.log", trace),
      tool("trace_2", "logs/request-trace.log", trace),
      tool("legacy", "src/legacy/parser.mjs", legacy),
    ],
  },
  ...Array.from({ length: 8 }, (_, index) => ({
    info: { id: `msg_continue_${index}`, sessionID, role: "user" },
    parts: [
      {
        id: `part_continue_${index}`,
        sessionID,
        messageID: `msg_continue_${index}`,
        type: "text",
        text: "Continue.",
      },
    ],
  })),
];
const durableStore = new Map([[sessionID, structuredClone(messages)]]);
const durableMutationCalls = [];
const durableHash = (value) =>
  createHash("sha256").update(JSON.stringify(value)).digest("hex");
const appLogs = [];
const sessionClient = new Proxy(
  {
    get: async ({ path }) =>
      durableStore.has(path.id)
        ? { data: { id: path.id } }
        : { error: { name: "NotFound" } },
    messages: async ({ path }) => ({
      data: structuredClone(durableStore.get(path.id) ?? []),
    }),
  },
  {
    get(target, property, receiver) {
      if (Reflect.has(target, property)) {
        return Reflect.get(target, property, receiver);
      }
      if (typeof property !== "string") return undefined;
      return async (...args) => {
        durableMutationCalls.push({ method: property, args });
        throw new Error(`unexpected durable session mutation: ${property}`);
      };
    },
  },
);
const client = {
  app: {
    log: async (entry) => {
      appLogs.push(entry);
    },
  },
  session: sessionClient,
};
const fetchDurableMessages = async () => {
  const response = await client.session.messages({ path: { id: sessionID } });
  return response.data;
};
const beforeHash = durableHash(await fetchDurableMessages());

const canonicalPayloadCharacters = (source) =>
  source.reduce(
    (total, message) =>
      total +
      message.parts.reduce((partTotal, part) => {
        if (part.type === "text" && part.ignored !== true) {
          return partTotal + (part.text?.length ?? 0);
        }
        if (part.type !== "tool") return partTotal;
        const result =
          part.state?.status === "completed"
            ? part.state.output ?? ""
            : part.state?.status === "error"
              ? part.state.error ?? ""
              : "";
        return (
          partTotal +
          JSON.stringify(part.state?.input ?? {}).length +
          result.length
        );
      }, 0),
    0,
  );

process.chdir(workspace);
const server = await serverModule.OpenCodeGlinerPrunePlugin({
  client,
  directory: workspace,
});
const registered = [];
const toasts = [];
await tuiModule.registerGlinerPruneCommand({
  command: {
    register: (factory) => {
      registered.push(...factory());
      return () => {};
    },
  },
  route: { current: { name: "session", params: { sessionID } } },
  state: { path: { directory: workspace } },
  ui: { toast: (toast) => toasts.push(toast) },
  lifecycle: { onDispose: () => () => {} },
  client: {},
});
const commands = new Map(registered.map((item) => [item.value, item]));

const run = async (name) => {
  const command = commands.get(`gliner-prune.${name}`);
  assert.ok(command?.onSelect, `missing ${name} command`);
  const start = performance.now();
  await command.onSelect();
  const result = toasts.at(-1);
  assert.equal(result?.variant, "success", `${name} failed: ${result?.message}`);
  return {
    message: result.message,
    milliseconds: Math.round(performance.now() - start),
  };
};

let transformed;
const report = {
  package: JSON.parse(
    await readFile(join(packageRoot, "package.json"), "utf8"),
  ).version,
  workingDirectory: process.cwd(),
  beforeHash,
};
try {
  report.setup = await run("setup");
  report.preview = await run("preview");
  assert.match(report.preview.message, /Preview: [3-5]\/5 tool interactions/);
  const tokenEstimate = report.preview.message.match(
    /~([\d,]+) → ~([\d,]+) estimated tokens/,
  );
  assert.ok(tokenEstimate, "preview did not report estimated token reduction");
  const estimatedBefore = Number(tokenEstimate[1].replaceAll(",", ""));
  const estimatedAfter = Number(tokenEstimate[2].replaceAll(",", ""));
  const estimatedReduction = 1 - estimatedAfter / estimatedBefore;
  assert.ok(
    estimatedReduction >= 0.7,
    `estimated reduction ${estimatedReduction.toFixed(3)} is below 0.7`,
  );
  report.estimatedTokens = {
    before: estimatedBefore,
    after: estimatedAfter,
    reduction: estimatedReduction,
  };

  report.apply = await run("apply");
  assert.match(report.apply.message, /Applied: [3-5]\/5 tool interactions/);

  report.active = await run("status");
  assert.match(report.active.message, /^Active:/);

  const providerOutput = { messages: structuredClone(messages) };
  await server["experimental.chat.messages.transform"]({}, providerOutput);
  transformed = providerOutput.messages;
  const transformedTools = transformed.flatMap((message) =>
    message.parts.filter((part) => part.type === "tool"),
  );
  assert.ok(
    transformedTools.length < 5,
    "provider transform did not remove any tool interactions",
  );
  const transformedText = JSON.stringify(transformed);
  assert.match(transformedText, /Expected quantity: 1200/);
  assert.match(transformedText, /Received quantity: 120/);
  assert.match(transformedText, /tests\/parser\.test\.mjs:6:10/);
  assert.match(transformedText, /Legacy compatibility fixture\. Do not modify\./);
  const actualBefore = canonicalPayloadCharacters(messages);
  const actualAfter = canonicalPayloadCharacters(transformed);
  const actualReduction = 1 - actualAfter / actualBefore;
  assert.ok(
    actualReduction >= 0.7,
    `actual transformed reduction ${actualReduction.toFixed(3)} is below 0.7`,
  );
  report.actualCharacters = {
    before: actualBefore,
    after: actualAfter,
    reduction: actualReduction,
  };
  const afterApplyHash = durableHash(await fetchDurableMessages());
  assert.equal(
    afterApplyHash,
    beforeHash,
    "durable messages changed after apply",
  );
  assert.deepEqual(
    durableMutationCalls,
    [],
    "apply attempted a durable session mutation",
  );

  report.reset = await run("reset");
  assert.match(report.reset.message, /full context restored/);

  report.inactive = await run("status");
  assert.match(report.inactive.message, /no active pruning/);

  const resetOutput = { messages: structuredClone(messages) };
  await server["experimental.chat.messages.transform"]({}, resetOutput);
  assert.deepEqual(resetOutput.messages, messages);
  const afterResetHash = durableHash(await fetchDurableMessages());
  assert.equal(afterResetHash, beforeHash, "durable messages changed after reset");
  assert.deepEqual(
    durableMutationCalls,
    [],
    "reset attempted a durable session mutation",
  );
  report.afterHash = afterResetHash;
  report.durableMutationCalls = durableMutationCalls;
  report.transformedToolCount = transformedTools.length;
  report.originalToolCount = 5;
  report.protectedFacts = {
    expected: true,
    received: true,
    location: true,
    legacyConstraint: true,
  };
  report.appLogEntries = appLogs.length;
} finally {
  await server.dispose();
}

await writeFile(
  join(gate, "report.json"),
  JSON.stringify(report, null, 2) + "\n",
);
console.log(JSON.stringify(report, null, 2));
