"""Incremental Analysis Controller

Manages incremental analysis of code repositories by tracking file changes
and only re-analyzing modified components, improving performance for large
codebases by avoiding full re-analysis on every run.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    """Represents a snapshot of a file's state at analysis time."""
    path: str
    content_hash: str
    last_modified: float
    size: int

    def has_changed(self, other: "FileSnapshot") -> bool:
        """Check if this snapshot differs from another."""
        return self.content_hash != other.content_hash


@dataclass
class IncrementalState:
    """Persisted state for incremental analysis tracking."""
    snapshots: Dict[str, FileSnapshot] = field(default_factory=dict)
    analyzed_files: Set[str] = field(default_factory=set)
    last_run_timestamp: Optional[float] = None


class IncrementalAnalysisController:
    """Controls incremental analysis by detecting and processing only changed files.

    Compares current file states against a persisted snapshot to determine
    which files need re-analysis, significantly reducing analysis time for
    incremental changes in large repositories.
    """

    STATE_FILE = ".codeboarding/.incremental_state.json"

    def __init__(self, repo_root: str, state_file: Optional[str] = None):
        self.repo_root = Path(repo_root)
        self.state_file = Path(state_file or self.STATE_FILE)
        self._state = IncrementalState()
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted incremental state from disk."""
        if not self.state_file.exists():
            logger.debug("No incremental state found, starting fresh.")
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            snapshots = {
                path: FileSnapshot(**snap)
                for path, snap in data.get("snapshots", {}).items()
            }
            self._state = IncrementalState(
                snapshots=snapshots,
                analyzed_files=set(data.get("analyzed_files", [])),
                last_run_timestamp=data.get("last_run_timestamp"),
            )
            logger.info("Loaded incremental state with %d file snapshots.", len(snapshots))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to load incremental state: %s. Resetting.", exc)
            self._state = IncrementalState()

    def save_state(self) -> None:
        """Persist current incremental state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "snapshots": {
                path: vars(snap)
                for path, snap in self._state.snapshots.items()
            },
            "analyzed_files": list(self._state.analyzed_files),
            "last_run_timestamp": self._state.last_run_timestamp,
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("Incremental state saved to %s.", self.state_file)

    def _compute_snapshot(self, file_path: Path) -> FileSnapshot:
        """Compute a snapshot for a given file."""
        stat = file_path.stat()
        content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        return FileSnapshot(
            path=str(file_path.relative_to(self.repo_root)),
            content_hash=content_hash,
            last_modified=stat.st_mtime,
            size=stat.st_size,
        )

    def get_changed_files(self, candidate_files: List[str]) -> Tuple[List[str], List[str]]:
        """Identify which files have changed since the last analysis run.

        Args:
            candidate_files: List of file paths (relative to repo root) to check.

        Returns:
            A tuple of (changed_files, unchanged_files).
        """
        changed, unchanged = [], []

        for rel_path in candidate_files:
            abs_path = self.repo_root / rel_path
            if not abs_path.exists():
                logger.debug("Skipping missing file: %s", rel_path)
                continue

            current_snapshot = self._compute_snapshot(abs_path)
            previous_snapshot = self._state.snapshots.get(rel_path)

            if previous_snapshot is None or current_snapshot.has_changed(previous_snapshot):
                changed.append(rel_path)
            else:
                unchanged.append(rel_path)

        logger.info(
            "Incremental check: %d changed, %d unchanged out of %d files.",
            len(changed), len(unchanged), len(candidate_files),
        )
        return changed, unchanged

    def update_snapshots(self, analyzed_files: List[str]) -> None:
        """Update stored snapshots for files that were successfully analyzed.

        Args:
            analyzed_files: List of file paths that were analyzed in this run.
        """
        import time

        for rel_path in analyzed_files:
            abs_path = self.repo_root / rel_path
            if abs_path.exists():
                self._state.snapshots[rel_path] = self._compute_snapshot(abs_path)
                self._state.analyzed_files.add(rel_path)

        self._state.last_run_timestamp = time.time()
        logger.debug("Updated snapshots for %d files.", len(analyzed_files))

    def invalidate(self, file_paths: Optional[List[str]] = None) -> None:
        """Invalidate cached state for specific files or all files.

        Args:
            file_paths: Files to invalidate. If None, clears all state.
        """
        if file_paths is None:
            self._state = IncrementalState()
            logger.info("Full incremental state invalidated.")
        else:
            for path in file_paths:
                self._state.snapshots.pop(path, None)
                self._state.analyzed_files.discard(path)
            logger.info("Invalidated %d file entries from incremental state.", len(file_paths))
