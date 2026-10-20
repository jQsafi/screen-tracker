"""
GitHub synchronization module.
Automates staging, committing, and pushing screenshots to a remote GitHub repository.
"""

import logging
import os
from pathlib import Path
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class GitHubSync:
    """Manages Git operations to push screenshots to GitHub."""

    def __init__(
        self,
        repo_dir: Path,
        remote: str = "origin",
        branch: str = "main",
        commit_prefix: str = "[Auto-Capture]",
    ):
        self.repo_dir = Path(repo_dir).resolve()
        self.remote = remote
        self.branch = branch
        self.commit_prefix = commit_prefix

    def is_git_repo(self) -> bool:
        """Check if target directory is inside an initialized Git repository."""
        res = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return res is not None and res.strip() == "true"

    def init_repo(self) -> bool:
        """Initialize git repo if not already created."""
        if not self.is_git_repo():
            res = self._run_git(["init"])
            if res is not None:
                logger.info("Initialized Git repository at %s", self.repo_dir)
                return True
            return False
        return True

    def commit_and_push(
        self, file_path: Path, app_name: str, timestamp: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Stage the screenshot file, commit it, and push to GitHub.
        Returns:
            (success: bool, commit_hash: Optional[str], error_message: Optional[str])
        """
        if not self.is_git_repo():
            msg = f"Directory {self.repo_dir} is not a Git repository."
            logger.warning(msg)
            return False, None, msg

        # Stage the file relative to repo root
        try:
            rel_path = file_path.resolve().relative_to(self.repo_dir)
        except ValueError:
            # File is outside repo directory
            rel_path = file_path

        stage_res = self._run_git(["add", str(rel_path)])
        if stage_res is None:
            return False, None, "Failed to git add screenshot file"

        # Check if there are staged changes
        status = self._run_git(["status", "--porcelain"])
        if not status or str(rel_path) not in status:
            logger.info("No changes to commit for %s", rel_path)
            return True, None, None

        # Commit
        commit_msg = f"{self.commit_prefix} {app_name} at {timestamp}"
        commit_res = self._run_git(["commit", "-m", commit_msg])
        if commit_res is None:
            return False, None, "Failed to commit screenshot"

        # Get latest commit hash
        commit_hash = self._run_git(["rev-parse", "HEAD"])
        if commit_hash:
            commit_hash = commit_hash.strip()

        # Push to remote
        logger.info("Pushing commit %s to %s/%s...", commit_hash[:7] if commit_hash else "", self.remote, self.branch)
        push_res = self._run_git(["push", self.remote, self.branch])
        if push_res is None:
            # Push failed (e.g. no remote set up, authentication required, or offline)
            err = (
                f"Failed to push to {self.remote}/{self.branch}. "
                "Ensure remote and credentials/SSH key are configured."
            )
            logger.warning(err)
            return False, commit_hash, err

        logger.info("Successfully pushed to GitHub: %s", commit_hash)
        return True, commit_hash, None

    def _run_git(self, args: list) -> Optional[str]:
        """Runs a Git command inside the repository directory."""
        try:
            cmd = ["git"] + args
            res = subprocess.run(
                cmd,
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            if res.returncode == 0:
                return res.stdout
            else:
                logger.debug("Git command %s returned error: %s", args, res.stderr.strip())
                return None
        except Exception as e:
            logger.error("Git execution failed: %s", e)
            return None
