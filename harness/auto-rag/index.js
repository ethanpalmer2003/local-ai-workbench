/** Narrow retrieval gate: code questions must consult CBM/Graphify before normal tools. */

import { randomUUID } from 'node:crypto';

export const inject = ['tools'];

// - model-facing names that count as index retrieval (CBM tools, the graphify
//   plugin's graph tools, MCP resource reads, and namespaced MCP equivalents)
const DEFAULT_RETRIEVAL = [
  String.raw`^cbm_`,
  String.raw`graphify`,
  String.raw`^(query_graph|get_node|get_neighbors|get_community|shortest_path|god_nodes|graph_stats)$`,
  String.raw`^read_mcp_resource$`,
  String.raw`^list_mcp_resource`,
  String.raw`^mcp__.*(cbm|codebase|graphify|knowledge).*`,
];

// - arming signals: a code verb is required; a bare file suffix never arms alone,
//   so mentioning a filename in plain discussion does not trigger retrieval-only mode
const VERB = /\b(function|method|class|caller|callee|symbol|trace|definition|reference|import|dependency|dependencies|architecture|refactor|test|pytest|bug|error|exception|stack trace|where is|where are|who calls|what calls|how does|how do|find the|find all|locate|implement|signature|fix)\b/i;
const SUFFIX = /\.(py|js|ts|md|yml|yaml|json|toml|bat|ps1|tsx|jsx|cpp|h|rs|go)\b/;

const DENY_REASON =
  'Retrieval gate: this looks like a code/architecture question, so consult the code index first ' +
  'with a cbm_* or graphify tool (for example cbm_search, cbm_trace, or query_graph). ' +
  'All other tools unlock after one successful index lookup.';

const STEER_TEXT =
  'Retrieval gate: answer this code question from the index. Call one cbm_* or graphify tool ' +
  '(cbm_search, cbm_trace, query_graph, or similar) and ground your answer in its result before using anything else.';

/** Recursively freeze a plain message the way createUserMessage would. */
function freeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const key of Object.keys(value)) freeze(value[key]);
    Object.freeze(value);
  }
  return value;
}

/** One identified, frozen user-role notice carrying our own source kind. */
function notice(text, summary) {
  const message = {
    role: 'user',
    content: [{ type: 'text', text }],
    source: { kind: 'auto-rag', form: 'notice', summary },
    id: randomUUID(),
  };
  return freeze(structuredClone(message));
}

/** Compile one `*`-wildcard pattern, or treat the entry as a RegExp source. */
function compilePattern(entry) {
  if (entry.includes('*') && !entry.startsWith('^')) {
    return new RegExp(`^${entry.replace(/[|\\{}()[\]^$+?.]/g, String.raw`\$&`).replaceAll('*', '.*')}$`, 'i');
  }
  return new RegExp(entry, 'i');
}

export function apply(ctx, config = {}) {
  const maxSteers = config.maxSteers ?? 2;
  if (!Number.isInteger(maxSteers) || maxSteers < 0) {
    throw new Error(`auto-rag: invalid maxSteers ${String(maxSteers)} (must be an integer >= 0)`);
  }
  const extraAllow = config.extraAllow ?? [];
  const extraRetrieval = config.extraRetrieval ?? [];
  const retrievalPatterns = [...DEFAULT_RETRIEVAL, ...extraRetrieval].map(compilePattern);
  const allowedNames = new Set(extraAllow);

  // - one gate state per live agent: armed by a code question, cleared by a lookup
  const states = new WeakMap();

  /** Whether a tool call counts as index retrieval (skill loads only count for RAG skills). */
  function isRetrieval(name, args) {
    if (allowedNames.has(name)) return false;
    if (name === 'skill') {
      const skillName = typeof args?.name === 'string' ? args.name : '';
      return /codebase|graphify|memory|search/i.test(skillName);
    }
    return retrievalPatterns.some((pattern) => pattern.test(name));
  }

  /** Fail open: when no retrieval tool is visible the gate cannot be satisfied, so allow. */
  function retrievalAvailable(agent) {
    try {
      return ctx.tools.definitions(agent).some((definition) => retrievalPatterns.some((pattern) => pattern.test(definition.name)));
    } catch {
      return false;
    }
  }

  ctx.on('agent/created', ({ agent }) => {
    states.delete(agent);
  });

  // - a fresh user message re-arms the gate when it looks like a code question
  ctx.on('agent/pre-step', ({ agent, messages }, next) => {
    const userText = messages
      .filter((message) => message.source?.kind === 'user')
      .map((message) => message.content
        .filter((block) => block.type === 'text')
        .map((block) => block.text)
        .join('\n'))
      .join('\n');
    if (userText.length > 0) {
      // - the suffix only refines: a verb must be present, otherwise a bare
      //   filename mention in plain discussion would arm the gate
      states.set(agent, {
        required: VERB.test(userText),
        satisfied: false,
        steers: 0,
      });
    }
    return next();
  });

  // - while retrieval is outstanding, deny everything but the index tools
  ctx.on('tools/pre-execute', async (exec, next) => {
    const state = exec.agent ? states.get(exec.agent) : undefined;
    if (state?.required !== true || state.satisfied === true) return next();
    if (isRetrieval(exec.name, exec.arguments)) return next();
    if (!retrievalAvailable(exec.agent)) return next();
    return { kind: 'deny', reason: DENY_REASON };
  });

  // - one successful lookup satisfies the gate; delegate everything downstream
  ctx.on('tools/post-execute', async (exec, result, next) => {
    const state = exec.agent ? states.get(exec.agent) : undefined;
    if (state?.required === true && state.satisfied === false
      && isRetrieval(exec.name, exec.arguments)
      && result.isError === false && Array.isArray(result.content) && result.content.length > 0) {
      state.satisfied = true;
    }
    return next();
  });

  // - a direct answer with no lookup gets steered back to the index, with a cap
  ctx.on('agent/turn-stopping', async ({ agent }) => {
    const state = states.get(agent);
    if (state?.required !== true || state.satisfied === true || state.steers >= maxSteers) return;
    state.steers += 1;
    agent.steer(notice(STEER_TEXT, `retrieval required (${state.steers}/${maxSteers})`));
  });
}
