#!/usr/bin/env python3
"""Experimental Bash-free virtual environment setup (fonts are a separate step).

Safe defaults: --check is read-only; --install-envs is explicit, preserves
working environments, and refuses to replace an existing broken environment.
This does not establish Windows/ARM64 compatibility of pinned package wheels.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 14)
ENV_SPECS = (
    (".venv_paddle", "requirements-paddle.txt",
     "import paddleocr, paddlex, onnxruntime, numpy"),
    (".venv", "requirements-helper.txt",
     "import fitz, PIL, reportlab, pypdf, fontTools"),
)


def supported_python(version: tuple[int, int]) -> bool:
    return MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE


def environment_python(directory: Path, *, platform_name: str | None = None) -> Path:
    if (sys.platform == "win32" if platform_name is None else platform_name == "win32"):
        return directory / "Scripts" / "python.exe"
    return directory / "bin" / "python"


def imports_work(interpreter: Path, code: str) -> bool:
    if not interpreter.is_file():
        return False
    try:
        return subprocess.run(
            [str(interpreter), "-c", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except OSError:
        return False


def plan(root: Path) -> list[tuple[Path, Path, str, str]]:
    entries = []
    for name, requirements_name, imports in ENV_SPECS:
        directory = root / name
        requirements = root / requirements_name
        if not requirements.is_file():
            raise RuntimeError(f"requirements file not found: {requirements}")
        interpreter = environment_python(directory)
        if imports_work(interpreter, imports):
            status = "REUSE"
        elif directory.exists():
            status = "BLOCKED_EXISTING_ENV"
        else:
            status = "CREATE"
        entries.append((directory, requirements, imports, status))
    return entries


def install_environments(entries: list[tuple[Path, Path, str, str]]) -> None:
    # Check all destinations first, so one known-broken environment cannot
    # cause the other environment to be installed or changed.
    if any(status == "BLOCKED_EXISTING_ENV" for _, _, _, status in entries):
        raise RuntimeError(
            "Existing unusable environment detected; setup stopped without "
            "replacing or deleting it. Inspect it and use a separate backup "
            "procedure before retrying."
        )
    for directory, requirements, imports, status in entries:
        if status == "REUSE":
            print(f"[SKIP] reusable environment: {directory}", flush=True)
            continue
        print(f"[CREATE] environment: {directory}", flush=True)
        venv.EnvBuilder(with_pip=True).create(str(directory))
        interpreter = environment_python(directory)
        subprocess.run(
            [str(interpreter), "-m", "pip", "install", "-r", str(requirements)],
            check=True,
        )
        if not imports_work(interpreter, imports):
            raise RuntimeError(
                f"Environment installation/import check failed: {directory}. "
                "The partial environment has been preserved for inspection."
            )
        print(f"[OK] environment verified: {directory}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental Python-only environment setup; fonts not installed."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true",
        help="Read-only environment/version inspection (default)",
    )
    mode.add_argument(
        "--install-envs", action="store_true",
        help="Explicitly create missing venvs and install requirements via pip",
    )
    args = parser.parse_args(argv)
    print(f"[INFO] base Python: {sys.executable}", flush=True)
    print(f"[INFO] version: {sys.version.split()[0]}", flush=True)
    print(f"[INFO] repository: {ROOT}", flush=True)
    if not supported_python(sys.version_info[:2]):
        print(
            "[ERROR] This pinned environment setup requires Python 3.10–3.13. "
            "Python 3.14 compatibility is not yet established. "
            "Select a supported base interpreter explicitly.",
            file=sys.stderr, flush=True,
        )
        return 2
    try:
        entries = plan(ROOT)
        for directory, _, _, status in entries:
            print(f"[PLAN] {status}: {directory}", flush=True)
        if args.install_envs:
            install_environments(entries)
            print(
                "[DONE] Python environments checked; font setup is a separate step.",
                flush=True,
            )
        else:
            print("[OK] read-only check; no files changed", flush=True)
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
