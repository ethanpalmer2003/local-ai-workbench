"""Editable Pi packages, CLI flags, environment and extension settings."""

from typing import Any

CONFIG: dict[str, Any] = {
    "core_package": "@earendil-works/pi-coding-agent",
    "extensions": [
        # Visual
        {"package": "pi-polish", "group": "visual", "enabled": True},
        {"package": "pi-context-bar", "group": "visual", "enabled": True},
        # Nonvisual
        {
            "package": "pi-lens",
            "group": "nonvisual",
            "enabled": True,
            "cli_args": ["--no-lens-context"],
            "environment": {
                "PI_LENS_NO_CONTEXT_INJECTION": "1",
                "PI_LENS_CONFIG_PATH": "{config_dir}/coding_agents/pi/lens.json",
                "PI_LENS_HOME": "{state_dir}/coding_agents/pi/lens",
                "PILENS_DATA_DIR": "{state_dir}/coding_agents/pi/lens/projects",
                "PI_LENS_DISABLE_LSP_INSTALL": "1",
                "PI_LENS_DISABLE_TOOL_INSTALL": "1",
                "VIRTUAL_ENV": "{venv}",
                "PATH": "{venv}/Scripts{path_separator}{PATH}",
            },
        },
        {"package": "pi-loop-police", "group": "nonvisual", "enabled": True},
        {"package": "pi-background", "group": "nonvisual", "enabled": True},
    ],
    "local_extensions": ["extensions/protected-paths.ts", "extensions/permission-gate.ts"],
    "default_tools": ["codemode", "tool_search"],
}
