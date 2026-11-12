import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { delimiter, join } from "node:path";
import { fileURLToPath } from "node:url";
import { newRun, writeReport } from "../../../shared/paths.mjs";

const started = performance.now();
const output = await newRun(import.meta.url);
const root = fileURLToPath(new URL("../../../../../", import.meta.url));
const workspace = join(output.temp, "workspace");
const agentDir = join(output.temp, "agent");
await mkdir(workspace, { recursive: true });
await mkdir(agentDir, { recursive: true });
const manifest = JSON.parse(execFileSync(join(root, ".venv/Scripts/python.exe"),
  ["-m", "scripts.config.coding_agents.pi.packages"], { cwd: root, encoding: "utf8" }));
for (const extension of manifest.extensions.filter(item => item.enabled !== false)) {
  for (const [name, value] of Object.entries(extension.environment || {})) {
    process.env[name] = value.replaceAll("{config_dir}", join(root, "scripts/config"))
      .replaceAll("{state_dir}", join(output.temp, "state")).replaceAll("{venv}", join(root, ".venv"))
      .replaceAll("{path_separator}", delimiter).replaceAll("{PATH}", process.env.PATH || "");
  }

}
process.env.PI_CODING_AGENT_DIR = agentDir;
const fixture = join(workspace, "fixture.py");
await writeFile(fixture, 'value: int = "wrong type"\n', "utf8");
await writeFile(join(workspace, "pyproject.toml"), '[tool.pyright]\npythonVersion = "3.13"\n', "utf8");
await writeFile(join(agentDir, "settings.json"), JSON.stringify({
  packages: manifest.extensions.filter(item => item.enabled !== false)
    .map(item => join(root, "frameworks/coding_agents/pi/node_modules", item.package)),
  defaultTools: manifest.default_tools.map(name => "+" + name),
}), "utf8");
process.chdir(workspace);
const sdk = await import(new URL("../../../../../frameworks/coding_agents/pi/node_modules/@earendil-works/pi-coding-agent/dist/index.js", import.meta.url));
sdk.initTheme("dark", false);
let session;
try {
  const loader = new sdk.DefaultResourceLoader({ cwd: workspace, agentDir, extensionFactories: [sdk.createCodemodeExtension()] });
  await loader.reload();
  const created = await sdk.createAgentSession({ cwd: workspace, agentDir, resourceLoader: loader,
    sessionManager: sdk.SessionManager.inMemory() });
  session = created.session;
  assert.equal(created.extensionsResult.errors.length, 0, JSON.stringify(created.extensionsResult.errors));
  const ui = session.extensionRunner.createContext().ui;
  await session.bindExtensions({ uiContext: { ...ui, notify: message => console.error(message) } });
  const active = session.getActiveToolNames();
  assert(active.includes("lens_diagnostics"), "Lens diagnostics are not active");
  assert(!active.includes("lsp_diagnostics"), "Retired LSP diagnostics are still active");
  assert(active.includes("codemode"), "Codemode is not active");
  const context = session.extensionRunner.createToolContext("lens-smoke", undefined);
  const tool = session.getToolDefinition("lens_diagnostics");
  let diagnostics;
  const deadline = Date.now() + 45000;
  do {
    diagnostics = await tool.execute("lens-smoke", { source: "lsp", scope: "paths", paths: [fixture] }, undefined, undefined, context);
    if (JSON.stringify(diagnostics).includes("reportAssignmentType")) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  await writeFile(join(output.artifacts, "diagnostics.json"), JSON.stringify(diagnostics, null, 2), "utf8");
  assert.match(JSON.stringify(diagnostics), /reportAssignmentType/, "Basedpyright did not report the known type error");
  const messages = [{ role: "user", content: "smoke check", timestamp: Date.now() }];
  const transformed = await session.extensionRunner.emitContext(messages);
  assert.deepEqual(transformed, messages, "Lens injected context despite the disabled setting");
  await writeFile(join(output.artifacts, "checks.json"), JSON.stringify({ active, contextInjectionDisabled: true,
    diagnosticFound: true, package: "pi-lens", flags: manifest.extensions.flatMap(item => item.cli_args || []) }, null, 2), "utf8");
  console.log("[OK] Pi Lens loads, detects the Python type error, and leaves context unchanged.");
} catch (error) {
  await writeFile(join(output.logs, "test.log"), String(error.stack || error), "utf8");
  console.error(error);
  process.exitCode = 1;
} finally {
  if (session) {
    await session.extensionRunner.emit({ type: "session_shutdown" });
    session.dispose();
  }
  await writeReport(output, { name: "harnesses/pi/lens_smoke", category: "model-free",
    status: process.exitCode ? "failed" : "completed", total_seconds: (performance.now() - started) / 1000 });
  console.log("[OUTPUT] " + output.root);
}
