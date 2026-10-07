"""APPROVAL invariant: a post is published only if its file reached `main` through a
merged Pull Request (D-002, D-004, D-020).

GitHub's "List pull requests associated with a commit" endpoint returns, for a commit on
the default branch, the merged PR that introduced it; a commit pushed directly returns no
merged PR. Docs: https://docs.github.com/rest/commits/commits (read 2026-10-08).
"""

from __future__ import annotations

import httpx

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"


class ApprovalError(RuntimeError):
    """Raised when GitHub cannot be asked whether a commit was approved."""


class GitHubClient:
    def __init__(self, http: httpx.Client, repository: str, token: str | None) -> None:
        self._http = http
        self._repository = repository
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def merged_pull_request(self, commit_sha: str, base_branch: str) -> dict | None:
        """Return the merged PR into `base_branch` that introduced `commit_sha`, if any."""
        url = f"{GITHUB_API_URL}/repos/{self._repository}/commits/{commit_sha}/pulls"
        response = self._http.get(url, headers=self._headers)
        if response.status_code != 200:
            raise ApprovalError(
                f"GitHub PR lookup failed ({response.status_code}): {response.text}"
            )
        for pull in response.json():
            if pull.get("merged_at") and pull.get("base", {}).get("ref") == base_branch:
                return pull
        return None
