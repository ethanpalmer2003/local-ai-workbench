/**
 * Protected Paths Extension (allow-list variant)
 *
 * Blocks write and edit operations outside C:/AI.
 * Read-only tools (read, ls, rg, grep, find) are unaffected.
 *
 * Based on examples/extensions/protected-paths.ts, inverted from a
 * deny-list to an allow-list.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { homedir } from "node:os";
import { resolve } from "node:path";

const ALLOW_ROOT = "C:/AI";

function canonicalize(input: string, cwd: string): string {
	let p = input.trim();
	if (p === "~" || p.startsWith("~/") || p.startsWith("~\\")) {
		const home = process.env.USERPROFILE ?? homedir();
		p = home + p.slice(1);
	}
	const abs = resolve(cwd, p);
	// Windows paths are case-insensitive; normalize for comparison
	return abs.toLowerCase().replaceAll("\\", "/");
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "write" && event.toolName !== "edit") {
			return undefined;
		}

		const raw = event.input.path as string;
		const path = canonicalize(raw, ctx.cwd);
		const root = ALLOW_ROOT.toLowerCase().replaceAll("\\", "/");

		const allowed = path === root || path.startsWith(root + "/");

		if (!allowed) {
			if (ctx.hasUI) {
				ctx.ui.notify(`Blocked write outside ${ALLOW_ROOT}: ${raw}`, "warning");
			}
			return { block: true, reason: `Path "${raw}" is outside ${ALLOW_ROOT}` };
		}

		return undefined;
	});
}
