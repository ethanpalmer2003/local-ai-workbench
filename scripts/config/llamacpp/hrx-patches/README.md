# Local HRX patches

These are additional routing experiments, not the community repository's `.diff`. They apply on top of the existing local Windows/codebook patches, whose complete tracked snapshots and base/upstream revisions are retained under `state/hrx/source-patches/`.

The installed latest-stack rebuild additionally uses `latest-loom-q4-bounds.patch` and `msvc-test-lambdas.patch`. Their hashes, complete source state and installed binary hashes are in `latest-stack-manifest.json`. HRX/ROCr patches are now committed on local integration branches; llama.cpp modifications remain exported working-tree patches.

- `iq2-iq3-s-decode-unfused.patch`: rejected because chunked prefill regressed. Do not apply it.
- `iq2-iq3-s-unfused-normal-output.patch`: supersedes that experiment and disables alternate output publication for the newly unfused IQ2_S/IQ3_S matmuls. See `corrected-manifest.json` for validation, hash and deployment status. Apply this patch alone, never both.

Source updates and patch application are separate from runtime installation. Review upstream changes and compatibility, check patch application, then rebuild an isolated candidate with matching source and patch revisions. Validate against CPU and the previous checkpoint before installing. Preserve the previous verified runtime for rollback. Existing source modifications have snapshots but have not yet been organized into separate Git commits.
