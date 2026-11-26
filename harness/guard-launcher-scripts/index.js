/** Refuses an ad-hoc script that starts or stops a service stack instead of its launcher. */

import { readFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const inject = ['tools'];

// - the workspace is two folders above this bundle (harness/guard-launcher-scripts)
const WORKSPACE = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const WRITE_TOOLS = new Set(['write', 'edit', 'apply_patch', 'str_replace_editor']);
// - what an ad-hoc stack script reaches for, and what a stack's own launcher already owns
const LAUNCHER_CALL = /launch_util|launch_module|scripts\.launchers/;
const SHELL_TOOLS = new Set(['pwsh', 'bash']);
const RUNS_PYTHON = /(?:^|[\s;&|])(?:uv run )?python[0-9.]*\s+(?:"([^"]+\.py)"|'([^']+\.py)'|(\S+\.py))/gi;

/** Whether a path is the repository's own code, where a launcher module belongs. */
function inWorkspace(path) {
  const absolute = isAbsolute(path) ? path : resolve(WORKSPACE, path);
  const within = relative(WORKSPACE, absolute);
  return Boolean(within) && !within.startsWith('..') && !isAbsolute(within);
}

/** Whether a written Python file would start or stop a stack itself. */
function adhocScript(path, content) {
  if (!path.toLowerCase().endsWith('.py') || !content || !LAUNCHER_CALL.test(content)) return false;
  return !inWorkspace(path);
}

/** Whether a shell command runs a Python file outside the workspace that reaches for the launchers. */
function adhocRun(command) {
  for (const match of command.matchAll(RUNS_PYTHON)) {
    const target = match[1] ?? match[2] ?? match[3] ?? '';
    if (!target || inWorkspace(target)) continue;
    try {
      const absolute = isAbsolute(target) ? target : resolve(WORKSPACE, target);
      if (LAUNCHER_CALL.test(readFileSync(absolute, 'utf8'))) return target;
    } catch {
      // - an unreadable target is not this guard's business
      continue;
    }
  }
  return '';
}

const REASON =
  'Ad-hoc stack script refused: a script that starts or stops services bypasses the launcher, which owns port ' +
  'clearing, supervision and teardown, so the leftover processes belong to nobody. Start the stack with ' +
  '`python -m scripts.launchers.<stack>` (koboldcpp for the chat stack), read readiness from its ports and ' +
  '`/v1/models`, and stop it with `python -m scripts.launchers.kill_all_services`. Closing the launcher window ' +
  'also stops it.';

export function apply(ctx) {
  ctx.effect(() =>
    ctx.tools.guard((exec) => {
      const args = exec.arguments ?? {};
      if (WRITE_TOOLS.has(exec.name)) {
        const path = String(args.file_path ?? args.path ?? '');
        const content = String(args.content ?? args.new_string ?? '');
        return adhocScript(path, content) ? REASON : undefined;
      }
      if (SHELL_TOOLS.has(exec.name)) {
        const command = typeof args.command === 'string' ? args.command : '';
        const target = command ? adhocRun(command) : '';
        if (target) return `${REASON} (refused running ${target})`;
      }
      return undefined;
    }),
  );
}
