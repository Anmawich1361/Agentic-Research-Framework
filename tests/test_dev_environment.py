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
        "check",
        "smoke-mock",
        "smoke-live-checkpoint",
    ):
        assert re.search(rf"^{re.escape(target)}:", makefile, flags=re.MULTILINE), target


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
