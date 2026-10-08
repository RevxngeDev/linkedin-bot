"""Thin wrapper over the `git` CLI, shared by the publisher and the generator.

Runs inside GitHub Actions, where actions/checkout leaves push credentials configured.
"""

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

    def remote_branch_exists(self, branch: str) -> bool:
        return bool(self._run("ls-remote", "--heads", "origin", branch).strip())

    def push_new_branch(self, branch: str, files: dict[Path, str], message: str) -> None:
        """Create `branch` from the remote base branch with `files`, commit and push it.

        The working tree returns to the base branch afterwards, so the files never land on
        it locally.
        """
        self._run("fetch", "origin", self._branch)
        self._run("switch", "--force-create", branch, f"origin/{self._branch}")
        try:
            for path, content in files.items():
                target = self._repo_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
            self._run("add", "--", *(str(p) for p in files))
            self._run(*self._identity, "commit", "--message", message)
            self._run("push", "origin", f"{branch}:{branch}")
        finally:
            self._run("switch", "--force", self._branch)

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
