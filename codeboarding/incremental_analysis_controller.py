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

    # Moved state file to project root level to avoid cluttering .codeboarding dir
    STATE_FILE = ".incremental_state.json"

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
                for path, snap in self._stat
