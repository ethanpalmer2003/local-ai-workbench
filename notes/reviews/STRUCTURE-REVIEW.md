# Structure review status

Canonical component keys cover model/install/config/launcher/test/batch paths.
`project_config.component()` owns paths and declared native-layout exceptions.
Shared assets retain one owner; procedure guides stay beside owning code.

[Folder rules](../../.agents/FOLDERS.md) define the contract;
`python -m scripts.review.structure_docs` checks paths, imports, links and doc budgets.
Current validation: [test status](../../scripts/tests/notes/STATUS.md).
Outstanding work: [TODO](../TODO.md).
