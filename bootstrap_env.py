"""
Bootstrap helper for the flipped XU ML variant.
- Ensures .venv exists
- Installs requirements
- Verifies critical files/modules
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_VENV = REPO_ROOT / ".venv"
DEFAULT_REQUIREMENTS = REPO_ROOT / "requirements.txt"


@dataclass(frozen=True)
class ProfileSpec:
    description: str
    required_files: Sequence[Path]
    required_modules: Sequence[str] = ("MetaTrader5",)


PROFILE_SPECS: dict[str, ProfileSpec] = {
    "xu-ml": ProfileSpec(
        description="Flipped XAUUSD ML stack",
        required_files=(
            Path("config/config_xu_ml.json"),
            Path("models/xauusd_entry_model.pkl"),
            Path("models/xauusd_entry_model_meta.json"),
        ),
        required_modules=("MetaTrader5", "pandas", "joblib"),
    ),
    "generic": ProfileSpec(description="Generic bootstrap", required_files=(), required_modules=("MetaTrader5",)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure the flipped ML environment is ready to launch.")
    parser.add_argument("--profile", required=True, help="Profile key (decides prerequisite checks).")
    parser.add_argument("--venv-path", type=Path, default=DEFAULT_VENV, help="Location of the shared venv.")
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="Requirements file to sync against.",
    )
    parser.add_argument("--skip-pip", action="store_true", help="Skip pip install step (for troubleshooting).")
    return parser.parse_args()


def run(cmd: Sequence[str], quiet: bool = False, **kwargs):
    if quiet:
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.STDOUT)
    else:
        print(f"[bootstrap] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def ensure_venv(venv_path: Path):
    if venv_path.exists():
        print(f"[bootstrap] Virtualenv already present at {venv_path}.")
        return
    print(f"[bootstrap] Creating virtualenv at {venv_path} ...")
    run([sys.executable, "-m", "venv", str(venv_path)])


def venv_python(venv_path: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    python_path = venv_path / scripts_dir / ("python.exe" if os.name == "nt" else "python")
    if not python_path.exists():
        raise RuntimeError(f"Unable to find python inside {venv_path}. Expected at {python_path}")
    return python_path


def sync_dependencies(python_path: Path, requirements: Path):
    if not requirements.exists():
        raise FileNotFoundError(f"requirements file not found: {requirements}")
    print("[bootstrap] Installing/upgrading dependencies...")
    try:
        run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"], quiet=True)
        run([str(python_path), "-m", "pip", "install", "-r", str(requirements)], quiet=True)
    except subprocess.CalledProcessError:
        print("[bootstrap] Pip install failed. Rerunning with verbose output...")
        run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(python_path), "-m", "pip", "install", "-r", str(requirements)])


def check_required_files(files: Iterable[Path]):
    for rel_path in files:
        full_path = (REPO_ROOT / rel_path).resolve()
        if not full_path.exists():
            raise FileNotFoundError(f"Required file missing: {rel_path}")


def verify_imports(python_path: Path, modules: Iterable[str]):
    for module in modules:
        run([str(python_path), "-c", f"import {module}"])


def main():
    args = parse_args()
    profile = PROFILE_SPECS.get(args.profile, PROFILE_SPECS["generic"])
    print(f"[bootstrap] Profile: {args.profile} — {profile.description}")

    ensure_venv(args.venv_path)
    python_path = venv_python(args.venv_path)

    if not args.skip_pip:
        sync_dependencies(python_path, args.requirements)
    else:
        print("[bootstrap] Skipping dependency sync per --skip-pip.")

    check_required_files(profile.required_files)
    verify_imports(python_path, profile.required_modules)

    for folder in ("logs", "logs/archives", "data", "models"):
        target = REPO_ROOT / folder
        target.mkdir(parents=True, exist_ok=True)

    print("[bootstrap] Environment ready.")


if __name__ == "__main__":
    main()
