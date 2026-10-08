"""Minimal GitHub REST client, shared by the publisher and the generator.

Endpoints per GitHub REST docs (API version 2026-03-10), read 2026-10-08:
- List pull requests associated with a commit (APPROVAL check, D-020)
- List pull requests filtered by head branch (generator dedupe, D-023)
- Create a pull request (one PR per draft, D-023)
"""

from __future__ import annotations

import httpx

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"


class GitHubError(RuntimeError):
    """Raised when a GitHub API call fails."""


class GitHubClient:
    def __init__(self, http: httpx.Client, repository: str, token: str | None) -> None:
        self._http = http
        self._repository = repository
        self._owner = repository.split("/", 1)[0]
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def merged_pull_request(self, commit_sha: str, base_branch: str) -> dict | None:
        """Return the merged PR into `base_branch` that introduced `commit_sha`, if any."""
        pulls = self._get(f"/repos/{self._repository}/commits/{commit_sha}/pulls")
        for pull in pulls:
            if pull.get("merged_at") and pull.get("base", {}).get("ref") == base_branch:
                return pull
        return None

    def pull_requests_for_branch(self, branch: str) -> list[dict]:
        """All PRs (open, closed or merged) whose head is `branch` in this repository."""
        return self._get(
            f"/repos/{self._repository}/pulls",
            params={"head": f"{self._owner}:{branch}", "state": "all"},
        )

    def create_pull_request(self, head: str, base: str, title: str, body: str) -> dict:
        url = f"{GITHUB_API_URL}/repos/{self._repository}/pulls"
        payload = {"head": head, "base": base, "title": title, "body": body}
        response = self._http.post(url, json=payload, headers=self._headers)
        if response.status_code != 201:
            raise GitHubError(
                f"Create pull request failed ({response.status_code}): {response.text}"
            )
        return response.json()

    def _get(self, path: str, params: dict[str, str] | None = None) -> list[dict]:
        response = self._http.get(f"{GITHUB_API_URL}{path}", params=params, headers=self._headers)
        if response.status_code != 200:
            raise GitHubError(f"GitHub GET {path} failed ({response.status_code}): {response.text}")
        return response.json()
