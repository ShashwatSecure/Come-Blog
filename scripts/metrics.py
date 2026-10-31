"""Print project metrics used in docs/production. Standard library only.

Usage (from the repo root):  backend/.venv/Scripts/python.exe scripts/metrics.py
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".git", "output", "_snapshots"}


def project_files(suffix: str) -> list[Path]:
    return [
        p for p in ROOT.rglob(f"*{suffix}")
        if not (set(p.relative_to(ROOT).parts) & SKIP)
    ]


def line_count(paths: list[Path]) -> int:
    return sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in paths)


def run(*args: str) -> str:
    result = subprocess.run(args, cwd=ROOT / "backend", capture_output=True, text=True, check=False)
    return (result.stdout + result.stderr).strip()


def main() -> None:
    py = project_files(".py")
    tests = [p for p in py if "tests" in p.parts]
    src = [p for p in py if p not in tests]
    print(f"python files        : {len(py)} ({len(src)} source, {len(tests)} test)")
    print(f"python lines        : {line_count(py)} ({line_count(src)} source, {line_count(tests)} test)")
    print(f"markdown docs lines : {line_count(project_files('.md'))}")
    print(f"static web lines    : {line_count(project_files('.html')) + line_count(project_files('.css')) + line_count(project_files('.js'))}")

    py_exe = sys.executable
    pytest_out = run(py_exe, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    summary = pytest_out.splitlines()[-1] if pytest_out else "n/a"
    print(f"pytest              : {summary}")
    ruff_out = run(py_exe, "-m", "ruff", "check", "app", "tests")
    found = re.search(r"Found (\d+) error", ruff_out)
    print(f"ruff findings       : {found.group(1) if found else 0}")


if __name__ == "__main__":
    main()
