"""Thin wrapper over the `git` CLI for the publish workflow (runs in GitHub Actions)."""

from __future__ import annotations

import subprocess
from pathlib import Path

PUSH_ATTEMPTS = 3


class GitError(RuntimeError):
    """Raised when a git command fails."""


class Git:
    def __init__(self, repo_dir: Path, branch: str, author_name: str, author_email: str) -> None:
        self._repo_dir = repo_dir
        self._branch = branch
        self._identity = ["-c", f"user.name={author_name}", "-c", f"user.email={author_email}"]

    def commit_that_added(self, path: Path) -> str | None:
        """SHA of the most recent commit that added `path`, or None if never added."""
        output = self._run("log", "--diff-filter=A", "--format=%H", "--", str(path))
        lines = output.split()
        return lines[0] if lines else None

    def commit_and_push(self, paths: list[Path], message: str) -> None:
        """Commit changes (including deletions) to `paths` and push, rebasing if needed."""
        self._run("add", "--all", "--", *(str(p) for p in paths))
        self._run(*self._identity, "commit", "--message", message)
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            try:
                self._run("push", "origin", f"HEAD:{self._branch}")
                return
            except GitError:
                if attempt == PUSH_ATTEMPTS:
                    raise
                self._run(*self._identity, "pull", "--rebase", "origin", self._branch)

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout
