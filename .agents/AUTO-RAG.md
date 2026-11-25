# Retrieval gate

The `auto-rag` profile bundle forces code questions through the index first. Behavior lives in `harness/auto-rag/index.js`; this page is only the readable account.

1. A fresh user message arms the gate when it matches code/architecture/debug/test wording or names a source file.
2. While armed, `tools/pre-execute` denies every tool except CBM (`cbm_*`), graphify graph tools, MCP resource reads, and RAG skill loads. One successful lookup disarms the gate.
3. A direct answer with no lookup is steered back to the index at `agent/turn-stopping`, at most twice per turn (`maxSteers`).
4. The gate fails open: if no retrieval tool is visible (index plugin down), everything is allowed.
5. Each new user message re-arms; state is per agent, so subagents are gated independently.

Limits: a lookup can succeed with useless results and still disarm the gate; the gate compels retrieval, not good use of it. The turn-steer cap means a stubborn answer eventually goes through. Config: `maxSteers` (default 2), `extraAllow` tool names, `extraRetrieval` regex sources.
