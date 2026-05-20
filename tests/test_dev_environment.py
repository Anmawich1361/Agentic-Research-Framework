import re
import subprocess
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_setuptools_src_layout() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"] == {
        "requires": ["setuptools>=69", "wheel"],
        "build-backend": "setuptools.build_meta",
    }
    assert config["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert config["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["src"],
        "include": ["agentic_research*"],
    }


def test_makefile_exposes_developer_environment_targets() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in (
        "setup",
        "reset-env",
        "doctor",
        "test",
        "check",
        "smoke-mock",
        "smoke-live-checkpoint",
    ):
        assert re.search(rf"^{re.escape(target)}:", makefile, flags=re.MULTILINE), target


def test_makefile_test_target_uses_repo_local_pytest_entrypoint() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(
        r"^test:[^\n]*\n(?P<body>(?:\t[^\n]*\n)+)",
        makefile,
        flags=re.MULTILINE,
    )

    assert match is not None
    body = match.group("body")
    assert "$(VENV_PYTEST)" in body or ".venv/bin/pytest" in body
    assert "PYTHONPATH=$(CURDIR)" in body
    assert "$(VENV_PYTHON) -m pytest" not in body


def test_reset_env_verifies_venv_removed_before_recreating() -> None:
    script = (PROJECT_ROOT / "scripts" / "reset_env.sh").read_text(encoding="utf-8")

    assert "deactivate" in script
    assert "chmod" in script
    assert "chflags" in script
    assert "xattr" in script
    assert "verify_venv_removed" in script
    assert "Unable to remove .venv" in script
    assert script.index("verify_venv_removed") < script.index("python3 -m venv .venv")


def test_doctor_env_checks_pytest_availability() -> None:
    script = (PROJECT_ROOT / "scripts" / "doctor_env.py").read_text(encoding="utf-8")

    assert ".venv/bin/pytest" in script
    assert "--version" in script
    assert "import pytest" in script
    assert "pytest.__file__" in script
    assert "make reset-env" in script


def test_doctor_env_script_has_cli_help() -> None:
    script = PROJECT_ROOT / "scripts" / "doctor_env.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "Diagnose the local agentic_research developer environment" in result.stdout
