import { mkdir, writeFile } from "node:fs/promises";
import { basename, dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

export async function writeReport(output, payload) {
  payload = { outcome: basename(dirname(output.root)), ...payload };
  const elapsed = payload.total_seconds == null ? "unknown (not recorded)" :
    `${payload.total_seconds.toFixed(3)} seconds (including startup and cleanup)`;
  await writeFile(join(output.artifacts, "report.json"), JSON.stringify(payload, null, 2) + "\n", "utf8");
  await writeFile(join(output.artifacts, "report.md"),
    `# ${payload.name}\n\nCategory: ${payload.category}\n\nOutcome: ${payload.outcome}\n\nStatus: ${payload.status}\n\n` +
    `Elapsed: ${elapsed}.\n\nDetailed results and timings are in this artifacts folder; server/tool logs are in ../logs/.\n`, "utf8");
}

export async function newRun(source, outcome = "unreviewed") {
  const tests = dirname(dirname(fileURLToPath(import.meta.url)));
  const casePath = relative(join(tests, "cases"), fileURLToPath(source));
  const caseName = casePath.slice(0, -extname(casePath).length);
  const id = (BigInt(Date.now()) * 1000000n + process.hrtime.bigint() % 1000000n).toString();
  if (!["verified", "no-gain", "inconclusive", "superseded", "unreviewed"].includes(outcome)) {
    throw new Error(`Unknown test outcome: ${outcome}`);
  }
  const root = join(tests, "output", caseName, outcome, id);
  const output = { root, logs: join(root, "logs"), artifacts: join(root, "artifacts"), temp: join(root, "temp") };
  await Promise.all([output.logs, output.artifacts, output.temp].map(path => mkdir(path, { recursive: true })));
  await writeFile(join(dirname(root), "README.md"),
    `# ${basename(caseName)}: ${outcome}\n\nRuns in this folder have outcome \`${outcome}\`.\n\n` +
    "Each run uses logs/, artifacts/, and temp/. Open artifacts/report.md for status and recorded elapsed time; " +
    "detailed evidence stays alongside it. Unknown timings and unreviewed status are not successful test results.\n",
    { encoding: "utf8", flag: "wx" }).catch(error => { if (error.code !== "EEXIST") throw error; });
  await writeReport(output, { name: caseName, category: casePath.split(/[\\/]/)[0], status: "unreviewed", total_seconds: null });
  return output;
}
