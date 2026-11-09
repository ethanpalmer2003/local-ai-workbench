# Runtime estimates

- Planning estimates, not measured guarantees. Include startup/loading, warmups, cleanup and requested sample count. Approval is required for runs expected over five minutes.
- Current pending scope: [TODO](../../../notes/TODO.md); procedures remain with their component guides.

| Scope | Approximate total |
| --- | --- |
| Model-free default regressions | about 30 seconds; measured after the suite grew |
| Focused report/silence fixtures | Under 5 seconds |
| Pi LSP/codemode integration | 5-15 seconds; starts tool processes |
| sd.cpp live workflow | 10-30 seconds |
| AudioCpp live workflow | 20-60 seconds |
| llama.cpp live workflow | 1-3 minutes |
| Kobold plus configured proxies | 30-90 seconds |
| DSH headless workflow | 2-4 minutes; desktop validation extra |
| Breeze short/long loaded/idle screen | About 4 minutes; bounded samples may remain incomplete |
| Five audio instruction samples | 40-90 seconds; listening extra |
| Four-client small harness subsets | About 10-15 minutes |
| Whole default live batch | 5-10 minutes |

- Profile/context/video grids can exceed these estimates substantially; calculate the actual matrix before starting.
- [Outcomes](OUTCOMES.md) owns measured findings; [ComfyUI procedure](../../benchmarks/personal/comfyui/README.md) owns video scope.
- Testing deferrals override estimates; no run is authorized by this table.
