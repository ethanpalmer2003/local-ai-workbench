# Harness overlay

Host configuration this workstation adds to [DeepSeek Harness](../.agents/DEEPSEEK-HARNESS.md), kept beside the
code it guards rather than in `scripts/state/`, which the harness discards and the scan guard refuses to walk.

1. [guard-deep-scan](guard-deep-scan/index.js) refuses a recursive shell scan, `glob` or `grep` over an ignored
   tree and names the bounded replacement. Behavior: [the guard](../.agents/DEEP-SCAN-GUARD.md).
2. The profile links the bundle by path, so this folder is a live dependency: `%USERPROFILE%\.dsh\profiles\desktop\package.json`
   carries `"@local/guard-deep-scan": "link:C:/AI/harness/guard-deep-scan"`, and `pnpm install` in that profile
   recreates the link. A harness start imports it; an edit reaches the next start, not the running one.
3. Anything machine-specific stays out: API routes, ports and account settings live in the profile's own
   `cordis.patch.yml`, which is not tracked here.
4. That profile is versioned separately in `overlay/`, a private repository this one ignores; its README carries
   the two copy commands that apply a change and capture a live one.
