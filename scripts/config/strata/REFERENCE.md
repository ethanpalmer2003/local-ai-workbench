# Experimental issue-3695 profile

- Source: [RX 7800 XT issue](https://github.com/Niko1221/Strata/issues/3695); local [native profile](reference-3695-32gb.json).
- Explicit selection; normal default remains unchanged.

```powershell
C:/AI/bat/launch_strata_pi_agent.bat --config C:/AI/scripts/config/strata/reference-3695-32gb.json
```

- Local machine: 16 GiB RX 7800 XT, 32 GiB host RAM; reference author used 96 GiB RAM. Installed engine/model versions also differ, so this is an adaptation, not reproduction.
- Native JSON owns memory/context/tokenizer/engine values; keep the effective runtime identity in evidence.
- Initial 12 GiB variant measured median 36.3 decode tok/s across five requests. Final 10 GiB profile passed the easy Pi Proverb check in 87.42 seconds with 378 output tokens.
- Easy-task completion does not establish harder coding/output-format quality, memory headroom for combined workloads or a general performance winner.
- Existing model-free checks predate later namespace changes; new type/path checks do not replace native workflow verification.
- [Strata configuration](README.md), [shared comparisons](../../benchmarks/coding_agents/README.md), [pending work](../../../notes/TODO.md).
