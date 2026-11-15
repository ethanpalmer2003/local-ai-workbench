# Duplicate check

`python -m scripts.review.similarity` is opt-in and needs a model: it starts the cataloged embedding model,
embeds every bullet and sentence in the maintained Markdown, and lists section pairs that share at least
two units (or one of 25+ words). This mode reads Markdown only, which is why its batch is
[review_document_similarity.bat](../../bat/checks/review_document_similarity.bat); Python sources are the
`--code` mode below, run by [review_code_similarity.bat](../../bat/checks/review_code_similarity.bat). Findings are pairs to review; the check never edits a document.
`--threshold`, `--top` and `--strict` tune it, and `--no-server` reuses a running server. On this machine the
bundled llama.cpp Vulkan build crashes on a batched embedding request, so start the ROCm build with
`HIP_VISIBLE_DEVICES=0` on port 8791 and pass `--no-server`; see the upstream entry for the signature.
Tables, code
fences and procedural lines are excluded. Each run writes
`scripts/state/generated/shared/similarity/<mode>/<run>/report.json`, which dates it and records a content
digest per file, so the next run says how many files changed since it. Those folders are prunable; the dated
[record](../../notes/reviews/EMBEDDINGS-2026-11-10.md) is what survives, so a page that quotes a pair count
names the date it came from. Evidence:
[embedding screen](../../notes/reviews/EMBEDDINGS-2026-11-10.md). Batches:
[review_document_similarity.bat](../../bat/checks/review_document_similarity.bat),
[review_code_similarity.bat](../../bat/checks/review_code_similarity.bat).

`--code` switches to functions: one chunk per function or method (AST, bodies of 3+ lines), tests skipped,
threshold 0.95, every pair reported. Code duplicates are weaker evidence, so read them as a list rather
than a defect count. It is part of the [repository review](README.md).
