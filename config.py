"""
Configuration module for the Screen Tracker application.
Loads settings from environment variables and CLI arguments with sensible defaults.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    # Interval between screen captures in seconds
    interval_seconds: float = 60.0

    # Directory where screenshots will be stored
    output_dir: Path = field(default_factory=lambda: Path("./screenshots"))

    # SQLite Database file path
    db_path: Path = field(default_factory=lambda: Path("./tracker.db"))

    # Whether to store raw image bytes (BLOB) inside the SQLite database
    store_image_blob: bool = False

    # OCR settings
    ocr_language: str = "eng"
    tesseract_cmd: Optional[str] = None

    # GitHub synchronization settings
    git_enabled: bool = False
    git_remote: str = "origin"
    git_branch: str = "main"
    git_repo_dir: Path = field(default_factory=lambda: Path("."))
    git_commit_prefix: str = "[Auto-Capture]"

    @classmethod
    def from_env(cls) -> "Config":
        """Instantiate configuration from environment variables."""
        return cls(
            interval_seconds=float(os.getenv("SCREEN_INTERVAL_SECONDS", "60.0")),
            output_dir=Path(os.getenv("SCREEN_OUTPUT_DIR", "./screenshots")),
            db_path=Path(os.getenv("SCREEN_DB_PATH", "./tracker.db")),
            store_image_blob=os.getenv("SCREEN_STORE_BLOB", "false").lower() in ("true", "1", "yes"),
            ocr_language=os.getenv("OCR_LANGUAGE", "eng"),
            tesseract_cmd=os.getenv("TESSERACT_CMD", None),
            git_enabled=os.getenv("GIT_ENABLED", "false").lower() in ("true", "1", "yes"),
            git_remote=os.getenv("GIT_REMOTE", "origin"),
            git_branch=os.getenv("GIT_BRANCH", "main"),
            git_repo_dir=Path(os.getenv("GIT_REPO_DIR", ".")),
            git_commit_prefix=os.getenv("GIT_COMMIT_PREFIX", "[Auto-Capture]"),
        )
