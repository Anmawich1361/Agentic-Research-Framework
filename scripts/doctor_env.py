from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGE_DIR = PROJECT_ROOT / "src" / "agentic_research"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose the local agentic_research developer environment."
    )
    parser.parse_args()

    print(f"branch: {_current_branch()}")
    print(f"python executable: {sys.executable}")
    _print_pip_executable()
    _print_sys_path()
    _print_pythonpath_status()

    package_file = _verify_import()
    print(f"agentic_research.__file__: {package_file}")
    _verify_package_path(package_file)
    _verify_arf_help()
    _verify_env_file()

    print("doctor: ok")
    return 0


def _current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _print_pip_executable() -> None:
    pip_path = Path(sys.executable).with_name("pip")
    if not pip_path.exists():
        resolved = shutil.which("pip")
        print(f"pip executable: {resolved or 'not found'}")
        _fail("pip executable is missing from .venv. Run 'make reset-env'.")

    print(f"pip executable: {pip_path}")
    result = subprocess.run(
        [str(pip_path), "--version"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        _fail("pip is not usable in .venv. Run 'make reset-env'.")


def _print_sys_path() -> None:
    print("sys.path:")
    for entry in sys.path:
        print(f"  {entry}")


def _print_pythonpath_status() -> None:
    pythonpath = os.environ.get("PYTHONPATH", "")
    repo_src = str((PROJECT_ROOT / "src").resolve())
    includes_repo_src = repo_src in {str(Path(item).resolve()) for item in pythonpath.split(os.pathsep) if item}
    print(f"PYTHONPATH includes repo src: {includes_repo_src}")


def _verify_import() -> Path:
    try:
        import agentic_research
    except ModuleNotFoundError as exc:
        _fail(
            "Could not import agentic_research. Run 'make reset-env', then 'make doctor'.",
            exc,
        )

    package_file_text = getattr(agentic_research, "__file__", None)
    if not package_file_text:
        _fail("agentic_research imported but did not expose __file__.")
    return Path(package_file_text).resolve()


def _verify_package_path(package_file: Path) -> None:
    if _is_relative_to(package_file, EXPECTED_PACKAGE_DIR):
        print("agentic_research path points to repo src: True")
        return

    _fail(
        "agentic_research is not importing from this repo's src/agentic_research. "
        f"Expected under {EXPECTED_PACKAGE_DIR}, got {package_file}. "
        "Run 'make reset-env', then 'make doctor'."
    )


def _verify_arf_help() -> None:
    arf = PROJECT_ROOT / ".venv" / "bin" / "arf"
    if not arf.exists():
        _fail("Missing .venv/bin/arf. Run 'make setup' or 'make reset-env'.")

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [str(arf), "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        _fail(
            ".venv/bin/arf --help failed. Run 'make reset-env', then 'make doctor'.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    print(".venv/bin/arf --help: ok")


def _verify_env_file() -> None:
    dotenv_path = PROJECT_ROOT / ".env"
    exists = dotenv_path.exists()
    print(f".env exists: {exists}")

    dotenv_values = _read_dotenv(dotenv_path) if exists else {}
    key_in_env = bool(os.environ.get("OPENAI_API_KEY"))
    key_in_dotenv = bool(dotenv_values.get("OPENAI_API_KEY"))
    print(f"OPENAI_API_KEY in process env: {key_in_env}")
    print(f"OPENAI_API_KEY in .env: {key_in_dotenv}")


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            _fail(f"Invalid .env line {line_number}; expected KEY=VALUE.")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key[0].isdigit() or not key.replace("_", "").isalnum():
            _fail(f"Invalid .env key on line {line_number}.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _fail(message: str, exc: Exception | None = None) -> None:
    print(f"doctor: failed: {message}", file=sys.stderr)
    if exc is not None:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
