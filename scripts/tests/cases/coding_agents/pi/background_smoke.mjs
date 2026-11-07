import assert from "node:assert/strict";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFile } from "node:fs/promises";
import { newRun, writeReport } from "../../../shared/paths.mjs";

const started = performance.now();
const output = await newRun(import.meta.url);
const root = fileURLToPath(new URL("../../../../../", import.meta.url));
const { loadExtensions } = await import(new URL("../../../../../frameworks/coding_agents/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js", import.meta.url));
const loaded = await loadExtensions([
  join(root, "frameworks/coding_agents/pi/node_modules/pi-background/extensions/background.ts"),
  join(root, "scripts/config/coding_agents/pi/extensions/permission-gate.ts"),
], root);
assert.deepEqual(loaded.errors, []);
const [background, gate] = loaded.extensions;
const hook = background.handlers.get("tool_call")[0];
for (const [input, expected] of [
  [{ command: "echo hello" }, 120],
  [{ command: "echo hello", timeout: 30 }, 30],
  [{ command: "echo hello", timeout: 900 }, 600],
  [{ command: "echo one && echo two" }, 120],
  [{ command: "echo hello 2>&1" }, 120],
  [{ command: "sleep 10 &", timeout: 30 }, undefined],
]) {
  await hook({ toolName: "bash", input }, {});
  assert.equal(input.timeout, expected);
}
const other = { command: "echo hello" };
await hook({ toolName: "bg_run", input: other }, {});
assert.equal(other.timeout, undefined);
for (const name of ["bash", "bg_run"]) {
  const blocked = await gate.handlers.get("tool_call")[0](
    { toolName: name, input: { command: "sudo echo test" } }, { hasUI: false });
  assert.equal(blocked.block, true);
}
await writeFile(join(output.artifacts, "checks.json"), JSON.stringify({
  normalTimeoutSeconds: 120, maximumTimeoutSeconds: 600,
  bareAmpersandRemovesTimeout: true, bgRunHasNoInjectedDeadline: true,
  permissionGateCoversBackground: true, commandsExecuted: false,
}, null, 2));
await writeReport(output, { name: "harnesses/pi/background_smoke", category: "model-free",
  status: "completed", total_seconds: (performance.now() - started) / 1000 });
console.log("[OK] Installed Background timeout hooks and command guard passed; no shell commands executed.");
console.log("[OUTPUT] " + output.root);
