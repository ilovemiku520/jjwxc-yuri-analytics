import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const children = [];
const appRoot = fileURLToPath(new URL("../..", import.meta.url));

function start(args, env = process.env) {
  const child = spawn(process.execPath, args, {
    cwd: appRoot,
    env,
    stdio: "inherit",
    windowsHide: true,
  });
  children.push(child);
  return child;
}

async function waitFor(url, child, label) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (child.exitCode !== null)
      throw new Error(`${label} exited before becoming ready`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(500) });
      if (response.ok) return;
    } catch {
      // The bounded local service is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${label} did not become ready`);
}

function runPlaywright() {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      ["node_modules/@playwright/test/cli.js", "test"],
      { cwd: appRoot, stdio: "inherit", windowsHide: true },
    );
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
}

function stopOwnedProcess(child) {
  if (!child.pid || child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    child.kill("SIGTERM");
  }
}

let exitCode = 1;
try {
  const mock = start(["tests/e2e/mock-api.mjs"]);
  await waitFor("http://127.0.0.1:8000/health/live", mock, "mock API");
  const web = start(
    [
      "node_modules/next/dist/bin/next",
      "start",
      "-H",
      "127.0.0.1",
      "-p",
      "3200",
    ],
    {
      ...process.env,
      PYURI_INTERNAL_API_URL: "http://127.0.0.1:8000",
      PYURI_COHORT_IMPORT_TOKEN: "e2e-internal-token",
    },
  );
  await waitFor("http://127.0.0.1:3200", web, "Next.js server");
  exitCode = await runPlaywright();
} finally {
  for (const child of children.reverse()) stopOwnedProcess(child);
}
process.exit(exitCode);
