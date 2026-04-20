from __future__ import annotations

from pathlib import Path
import os


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def local_bin_dir() -> Path:
    return project_root() / "bin"


def resolve_binary(binary_name: str) -> str:
    """Resolve binary from local project bin first, then PATH."""
    candidate = local_bin_dir() / f"{binary_name}.exe"
    if candidate.exists():
        return str(candidate)
    return binary_name


def build_subprocess_env() -> dict[str, str]:
    """Build env with project-local bin prepended to PATH."""
    env = dict(os.environ)
    bin_dir = local_bin_dir()
    if bin_dir.exists():
        existing = env.get("PATH", "")
        env["PATH"] = f"{bin_dir}{os.pathsep}{existing}" if existing else str(bin_dir)
    return env

