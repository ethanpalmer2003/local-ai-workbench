# Review-gate cases

One test module per gate module in [scripts/review](../../../review): comments, docs, layout,
network timeouts, public audit, the gate's own consent, similarity and typography. A new gate
arrives with its case here, and the class is registered in [run.py](../../run.py) so the default
suite collects it.

- The gate itself is a procedure, not a test: `python -m scripts.review`. What each module enforces
  and its cost: [review README](../../../review/README.md), [tooling](../../../review/TOOLS.md).
- Cases here stay model-free: they exercise chunking, units, findings and boundaries, never the
  embedding server itself. The opt-in run is `python -m scripts.review.similarity`.
