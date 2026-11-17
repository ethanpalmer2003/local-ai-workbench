# Review-gate cases

One test module per gate module in [checks](checks): comments, docs, layout, network timeouts,
owned tokens, public audit, similarity and typography. A new gate arrives with its case in
[checks](checks), and the class is registered in [run.py](../../run.py) so the default suite collects
it. The runner, the audit and the examples page keep theirs at this level.

- The gate itself is a procedure, not a test: `python -m scripts.review`. What each module enforces
  and its cost: [review README](../../../review/README.md), [tooling](../../../review/TOOLS.md).
- Cases here stay model-free: they exercise chunking, units, findings and boundaries, never the
  embedding server itself. The opt-in run is `python -m scripts.review.checks.similarity`.
