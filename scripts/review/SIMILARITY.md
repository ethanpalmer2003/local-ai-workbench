# Duplicate check

`python -m scripts.review.similarity` is opt-in and needs a model: it starts the cataloged embedding model,
embeds every bullet and sentence in the maintained Markdown, and lists section pairs that share at least
two units (or one of 25+ words). Findings are pairs to review; the check never edits a document.
`--threshold`, `--top` and `--strict` tune it, and `--no-server` reuses a running server. Tables, code
fences and procedural lines are excluded. Each report records a content digest per file, so the next run
says how many files changed since it. Evidence:
[embedding screen](../../notes/reviews/EMBEDDINGS-2026-11-10.md). Batches:
[check_similarity.bat](../../bat/review/check_similarity.bat),
[check_code_similarity.bat](../../bat/review/check_code_similarity.bat).

`--code` switches to functions: one chunk per function or method (AST, bodies of 3+ lines), tests skipped,
threshold 0.95, every pair reported. Code duplicates are weaker evidence, so read them as a list rather
than a defect count. It is part of the [repository review](README.md).
