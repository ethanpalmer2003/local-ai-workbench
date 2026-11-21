# Saved HRX local work

One git bundle per repository holds the commits the local `codex/*` branches carry that no remote
has. Patches were tried first and rejected: the llama.cpp branches carry a squashed development
history whose exported patch is 125 MB, past the host's file limit, while the same commits as a
bundle are 0.2 MB. Restore a branch with `git fetch <bundle> '<ref>'` in that checkout, or read it
in place with `git bundle verify`.

`manifest.json` records each branch, every local-only commit, the remote head it was compared with,
and whether `git cherry` shows upstream already carrying an equivalent. The bundles exclude
`53d443cd0` in llama.cpp, the squashed development history that upstream rewrote; that commit exists
only in the local branch and is named here so it is not mistaken for lost work.
