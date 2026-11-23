/** Refuses a filesystem scan that would walk the local, ignored trees. */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const inject = ['tools'];

const SHELL_TOOLS = new Set(['pwsh', 'bash']);
const PATH_TOOLS = new Set(['glob', 'grep']);
// - the workspace is two folders above this bundle (harness/guard-deep-scan), so the lists come from the
//   ignore files that already decide what is local instead of a second copy that can disagree with them
const WORKSPACE = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
// - a cache repeats inside packages, so it is heavy wherever it appears even though one ignore file names
//   one location; every other name is heavy exactly where its ignore file puts it
const REPEATING = ['.git', '.venv', 'node_modules', '__pycache__', '.ruff_cache'];
const RECURSIVE = /-rec(?:urse)?\b|--recurse|--recursive|-r\s+\S+\s+\.|\bfind\s+[^\s]+\s+-name|\bdu\s+-a/i;
// - a call that names its root with one of these is bounded by that root, whatever the spelling
const PATH_FLAG = /-path\b|-literalpath\b|--path\b/i;
// - a recursion rooted here walks a heavy tree without spelling its name: `scripts` holds all three
//   run-output trees, so a scan of the whole source tree is already a 60k-file walk
const SCAN_ROOTS = [
  '\\.',
  'scripts',
  'scripts[\\\\/]tests',
  'scripts[\\\\/]benchmarks',
  'c:[\\\\/]ai',
  'c:[\\\\/]ai[\\\\/]scripts',
];
const ABOVE_HEAVY = new RegExp(`(^|[\\s\\/="'])(${SCAN_ROOTS.join('|')})(?=[\\s"']|$)`, 'i');

/** The directory patterns one ignore file declares, split into root names and workspace-relative trees. */
function ignoredTrees(directory, prefix = '') {
  const roots = [];
  const trees = [];
  let text = '';
  try {
    text = readFileSync(join(directory, '.gitignore'), 'utf8');
  } catch {
    return { roots, trees };
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    // - a negation, a comment, a file pattern and a mid-path glob are not a folder this guard names
    if (!line || line.startsWith('#') || line.startsWith('!') || !line.endsWith('/')) continue;
    if (line.slice(0, -1).includes('*') || line.includes('?')) continue;
    const pattern = line.replace(/^\//, '').replace(/\/$/, '');
    if (pattern.includes('/')) {
      trees.push([prefix, pattern].filter(Boolean).join('/'));
    } else if (prefix && !REPEATING.includes(pattern)) {
      // - a folder named inside a subdirectory ignore file belongs to that tree, not to every path
      trees.push(`${prefix}/${pattern}`);
    } else if (!REPEATING.includes(pattern)) {
      roots.push(pattern);
    }
  }
  return { roots, trees };
}

/** Every heavy name and tree the ignore files and the repeating caches declare. */
function heavyLists() {
  const root = ignoredTrees(WORKSPACE);
  const scripts = ignoredTrees(join(WORKSPACE, 'scripts'), 'scripts');
  return {
    roots: [...new Set([...root.roots, ...scripts.roots, ...REPEATING])],
    trees: [...new Set([...root.trees, ...scripts.trees])],
  };
}

const HEAVY = heavyLists();

/** Drop quoted substrings, so a flag written into a file is not read as a flag on the command line. */
function unquoted(command) {
  return command.replace(/"[^"]*"/g, '""').replace(/'[^']*'/g, "''");
}

/** Normalize separators so one pattern matches a Windows path, a POSIX path and a relative one. */
function normalize(value) {
  return value.replace(/\\/g, '/');
}

/** Whether a path names one of the heavyweight trees, by where that name is heavy. */
export function heavyPath(value) {
  const path = normalize(value).toLowerCase().replace(/^c:\/ai\/?/, '');
  const parts = path.split('/');
  if (HEAVY.roots.includes(parts[0])) return true;
  if (parts.some((part) => REPEATING.some((name) => part === name || part.startsWith(`${name}-`)))) return true;
  return HEAVY.trees.some((tree) => path.includes(tree));
}

/** Read the command string from a shell call, or '' when the call is not a shell command. */
function commandOf(exec) {
  if (!SHELL_TOOLS.has(exec.name)) return '';
  const args = exec.arguments ?? {};
  const command = args.command ?? args.cmd ?? '';
  return typeof command === 'string' ? command : '';
}

/** Read the `path` argument of a search call, or '' when the call is not one or names no path. */
function searchPathOf(exec) {
  if (!PATH_TOOLS.has(exec.name)) return '';
  const args = exec.arguments ?? {};
  const path = args.path;
  return typeof path === 'string' ? path : '';
}

/** Whether a path-shaped word in the command names a heavy tree, which is how `-Path data` is read. */
function heavyWord(command) {
  for (const raw of command.split(/\s+/)) {
    const token = raw.replace(/^["']|["',;]+$/g, '').replace(/[),]+$/, '');
    if (!token || token.startsWith('-')) continue;
    if (heavyPath(token)) return true;
  }
  return false;
}

/** Why a recursive shell command would walk a heavy tree, or '' when it is bounded. */
export function unboundedScan(command) {
  const text = unquoted(command);
  if (!RECURSIVE.test(text)) return '';
  if (heavyWord(command)) return 'it names a local ignored tree';
  if (ABOVE_HEAVY.test(text)) return 'its root contains the ignored trees under scripts';
  // - a recursive flag with no root at all starts at the working directory, which is the workspace root
  if (!PATH_FLAG.test(text) && !text.includes('/') && !text.includes('\\')) {
    return 'it names no folder, so it starts at the workspace root';
  }
  return '';
}

export function apply(ctx) {
  ctx.effect(() =>
    ctx.tools.guard((exec) => {
      const command = commandOf(exec);
      const unbounded = command ? unboundedScan(command) : '';
      // - both search tools match at any depth, so naming a heavy tree is already the recursive form
      const path = searchPathOf(exec);
      const heavySearch = Boolean(path) && heavyPath(path);
      if (!unbounded && !heavySearch) return undefined;
      return (
        'Scan of a local ignored tree (data, frameworks, trash, .git, .venv, node_modules, caches or run ' +
        `output) is refused: ${unbounded || 'it names a local ignored tree'}, and a scan there walks ` +
        'hundreds of thousands of files and runs for minutes. Name the one folder you want, or use the ' +
        'depth-bounded locator, python -m scripts.tools.locate_files .gguf. The bounded alternative per ' +
        'question is in .agents/CODE-SEARCH.md, and .agents/README.md indexes every rule document.'
      );
    }),
  );
}
