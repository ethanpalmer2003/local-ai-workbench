# Strata with Pi

```powershell
C:/AI/bat/launch_strata_pi_agent.bat
C:/AI/bat/launch_strata_pi_agent.bat --no-start
C:/AI/bat/launch_strata_pi_agent.bat --config C:/path/to/native-config.json
```

- Reuse a ready backend from saved native settings; model/auth/context/image capability come from that server.
- Otherwise launch with Strata's bundled Python and the selected native JSON. New backend starts reject inherited MCP servers; explicit `strata_mcp` access is separate.
- `STRATA_SERVICE` owns launcher selection/port/timeouts; [native configuration](../../config/strata/README.md).
- Pi owns prompts/tools/extensions/sessions under `state/coding_agents/pi/agent`; provider route is added beside llama.cpp. Credentials come from environment, not source literals.
- A reused backend remains running. A task-owned backend stops with Pi, including failed startup. Occupied ports are refused.
- New launcher logs: `state/logs/strata/`; native desktop/engine state remains app-managed.
- The registered native `frameworks/Strata` casing is an explicit path-map exception.
- [Experimental profile](../../config/strata/REFERENCE.md), [comparisons](../../benchmarks/coding_agents/README.md).
