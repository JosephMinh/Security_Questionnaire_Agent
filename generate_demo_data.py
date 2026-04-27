"""Demo workspace setup and reset entrypoint for the Security Questionnaire Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from rag import MANIFEST_FILE_NAME, RUNTIME_DIRECTORIES, SEED_TO_RUNTIME_PATHS


@dataclass(frozen=True)
class WorkspaceCopyResult:
    """One copied seed asset and the runtime path it was written to."""

    source_path: Path
    runtime_path: Path


def ensure_runtime_directories() -> tuple[Path, ...]:
    """Create the planned runtime directories when they do not already exist."""
    for directory in RUNTIME_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIRECTORIES


def copy_seed_assets() -> tuple[WorkspaceCopyResult, ...]:
    """Copy the curated seed files into the runtime workspace."""
    copied_assets: list[WorkspaceCopyResult] = []
    for source_path, runtime_path in SEED_TO_RUNTIME_PATHS:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, runtime_path)
        copied_assets.append(
            WorkspaceCopyResult(
                source_path=source_path,
                runtime_path=runtime_path,
            )
        )
    return tuple(copied_assets)


def prepare_demo_workspace() -> tuple[WorkspaceCopyResult, ...]:
    """Create the runtime workspace and populate it with the curated seed assets."""
    ensure_runtime_directories()
    return copy_seed_assets()


def main() -> int:
    """Run the setup path used by the UI's Load Demo Workspace action."""
    copied_assets = prepare_demo_workspace()
    print("Prepared demo workspace.")
    print(f"Manifest file name reserved for later setup beads: {MANIFEST_FILE_NAME}")
    for asset in copied_assets:
        print(f"{asset.source_path} -> {asset.runtime_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MANIFEST_FILE_NAME",
    "RUNTIME_DIRECTORIES",
    "SEED_TO_RUNTIME_PATHS",
    "WorkspaceCopyResult",
    "copy_seed_assets",
    "ensure_runtime_directories",
    "main",
    "prepare_demo_workspace",
]
