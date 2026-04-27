"""Demo workspace setup and reset entrypoint for the Security Questionnaire Agent."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

from rag import (
    CHROMA_DIR,
    DATA_DIR,
    MANIFEST_FILE_NAME,
    OUTPUTS_DIR,
    RUNTIME_DIRECTORIES,
    SEED_TO_RUNTIME_PATHS,
    WORKSPACE_HASH_DIRECTORIES,
)


@dataclass(frozen=True)
class WorkspaceCopyResult:
    """One copied seed asset and the runtime path it was written to."""

    source_path: Path
    runtime_path: Path


@dataclass(frozen=True)
class CleanupResult:
    """One runtime artifact removed during setup cleanup."""

    removed_path: Path


@dataclass(frozen=True)
class ManifestEntry:
    """Hash metadata for one runtime workspace file."""

    relative_path: str
    sha256: str
    size_bytes: int


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


def iter_runtime_files(root_directory: Path) -> tuple[Path, ...]:
    """Return stable, sorted runtime files under one workspace directory."""
    return tuple(
        path
        for path in sorted(root_directory.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    )


def clear_directory_contents(directory: Path) -> tuple[CleanupResult, ...]:
    """Remove runtime artifacts from one directory while preserving the directory itself."""
    removed_artifacts: list[CleanupResult] = []
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.name == ".gitkeep":
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed_artifacts.append(CleanupResult(removed_path=path))
            continue
        if path.is_dir():
            path.rmdir()
    return tuple(removed_artifacts)


def clear_output_artifacts() -> tuple[CleanupResult, ...]:
    """Clear prior output files without removing the output directory itself."""
    return clear_directory_contents(OUTPUTS_DIR)


def reset_index_cache() -> tuple[CleanupResult, ...]:
    """Clear only the local Chroma cache directory when explicitly requested."""
    return clear_directory_contents(CHROMA_DIR)


def file_sha256(path: Path) -> str:
    """Compute a stable SHA-256 digest for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest_entries() -> tuple[ManifestEntry, ...]:
    """Hash the runtime questionnaire and evidence files for manifest output."""
    entries: list[ManifestEntry] = []
    for root_directory in WORKSPACE_HASH_DIRECTORIES:
        for path in iter_runtime_files(root_directory):
            entries.append(
                ManifestEntry(
                    relative_path=str(path.relative_to(DATA_DIR)),
                    sha256=file_sha256(path),
                    size_bytes=path.stat().st_size,
                )
            )
    return tuple(entries)


def manifest_path() -> Path:
    """Return the runtime manifest path."""
    return DATA_DIR / MANIFEST_FILE_NAME


def write_workspace_manifest() -> Path:
    """Write the current runtime workspace manifest with file-level hashes."""
    entries = build_manifest_entries()
    combined_digest = hashlib.sha256()
    for entry in entries:
        combined_digest.update(entry.relative_path.encode("utf-8"))
        combined_digest.update(b"\0")
        combined_digest.update(entry.sha256.encode("utf-8"))
        combined_digest.update(b"\0")

    payload = {
        "manifest_version": 1,
        "workspace_hash": combined_digest.hexdigest(),
        "files": [
            {
                "relative_path": entry.relative_path,
                "sha256": entry.sha256,
                "size_bytes": entry.size_bytes,
            }
            for entry in entries
        ],
    }
    path = manifest_path()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    """Parse CLI flags for the setup script."""
    parser = argparse.ArgumentParser(
        description="Prepare the demo workspace from the curated seed assets."
    )
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="Clear only the local Chroma index cache before the next build.",
    )
    return parser.parse_args()


def prepare_demo_workspace(*, reset_index: bool = False) -> tuple[WorkspaceCopyResult, ...]:
    """Create the runtime workspace, clean it safely, and populate it with seed assets."""
    ensure_runtime_directories()
    copied_assets = copy_seed_assets()
    clear_output_artifacts()
    if reset_index:
        reset_index_cache()
    write_workspace_manifest()
    return copied_assets


def main() -> int:
    """Run the setup path used by the UI's Load Demo Workspace action."""
    args = parse_args()
    copied_assets = prepare_demo_workspace(reset_index=args.reset_index)
    print("Prepared demo workspace.")
    print(f"Workspace manifest: {manifest_path()}")
    print(f"Index reset requested: {args.reset_index}")
    for asset in copied_assets:
        print(f"{asset.source_path} -> {asset.runtime_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MANIFEST_FILE_NAME",
    "RUNTIME_DIRECTORIES",
    "SEED_TO_RUNTIME_PATHS",
    "CleanupResult",
    "ManifestEntry",
    "WorkspaceCopyResult",
    "build_manifest_entries",
    "clear_directory_contents",
    "clear_output_artifacts",
    "copy_seed_assets",
    "ensure_runtime_directories",
    "file_sha256",
    "main",
    "manifest_path",
    "parse_args",
    "prepare_demo_workspace",
    "reset_index_cache",
    "write_workspace_manifest",
]
