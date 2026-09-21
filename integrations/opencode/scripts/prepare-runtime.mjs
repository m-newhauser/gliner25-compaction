import { cp, copyFile, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const repositoryRoot = fileURLToPath(new URL("../../../", import.meta.url));
const runtime = join(packageRoot, "dist", "runtime");

await rm(runtime, { recursive: true, force: true });
await mkdir(join(runtime, "src"), { recursive: true });
await mkdir(join(runtime, "scripts"), { recursive: true });
await copyFile(
  join(repositoryRoot, "LICENSE"),
  join(packageRoot, "dist", "LICENSE"),
);
await copyFile(
  join(repositoryRoot, "pyproject.toml"),
  join(runtime, "pyproject.toml"),
);
await copyFile(join(repositoryRoot, "uv.lock"), join(runtime, "uv.lock"));
await copyFile(
  join(repositoryRoot, "scripts", "download_model.py"),
  join(runtime, "scripts", "download_model.py"),
);
await cp(
  join(repositoryRoot, "src", "gliner25_context_compaction"),
  join(runtime, "src", "gliner25_context_compaction"),
  {
    recursive: true,
    filter: (source) =>
      !source.includes("__pycache__") &&
      !source.endsWith(".pyc") &&
      !source.endsWith("/worker.py"),
  },
);
