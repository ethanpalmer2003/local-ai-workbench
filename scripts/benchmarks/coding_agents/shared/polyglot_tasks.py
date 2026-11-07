"""Load upstream exercises and unchanged tests for the existing client runner."""

from scripts.benchmarks.coding_agents.shared.framework_tasks import CodingTask
from scripts.config import project_config as project_cfg


def load_tasks() -> tuple[CodingTask, ...]:
    root = project_cfg.BENCHMARK_TOOLS_DIR / "aider-polyglot/python/exercises/practice"
    tasks = []
    for name in ("wordy", "transpose", "phone-number", "proverb", "grade-school"):
        folder = root / name
        files = {
            path.name: path.read_text(encoding="utf-8")
            for path in folder.glob("*.py")
            if not path.name.endswith("_test.py")
        }
        instructions = (folder / ".docs/instructions.md").read_text(encoding="utf-8")
        if name == "transpose":
            # - optional reference triggers LittleCoder's research classifier on this offline task
            instructions = instructions.replace("See [transpose][].", "").replace(
                "[transpose]: https://en.wikipedia.org/wiki/Transpose", ""
            )
        test_path = next(folder.glob("*_test.py"))
        tests = test_path.read_text(encoding="utf-8")
        files[test_path.name] = tests
        instructions += "\nUse the provided upstream unit tests as the specification. Edit implementation files only."
        tasks.append(CodingTask(name, instructions, files, tests + "\nunittest.main()\n"))
    return tuple(tasks)
