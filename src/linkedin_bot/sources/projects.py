"""Collect raw inputs about watched repos (Phase 3, D-018, D-029).

Only public metadata of repos listed in `config/watched_repos.yml` is read (DATA SOURCES
invariant). This module gathers material; it never writes post text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

DEFAULT_CONFIG_PATH = Path("config/watched_repos.yml")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
# Keep each request well under Groq's free-plan 8K tokens/minute (D-024).
MAX_README_CHARS = 6000
MAX_COMMITS = 40
MAX_FILES = 60
# Posts are written in Spanish (D-009): prefer a Spanish README when the repo has one.
SPANISH_README_PATHS = ("README.es.md", "README_es.md", "README.es-ES.md")


class SourceError(ValueError):
    """Raised when the watched-repos configuration is invalid."""


@dataclass(frozen=True)
class WatchConfig:
    repos: list[str]
    update_interval_days: int


@dataclass(frozen=True)
class ProjectSnapshot:
    repo: str
    url: str
    description: str
    languages: list[str]
    readme: str
    head_sha: str


@dataclass(frozen=True)
class ProjectActivity:
    base_sha: str
    head_sha: str
    commits: list[str] = field(default_factory=list)  # "sha7 first line of message"
    files: list[str] = field(default_factory=list)  # "status path"
    total_commits: int = 0


class RepoReader(Protocol):
    def get_repository(self, repo: str) -> dict: ...
    def get_languages(self, repo: str) -> dict[str, int]: ...
    def head_sha(self, repo: str, branch: str) -> str: ...
    def get_readme(self, repo: str) -> str | None: ...
    def get_file(self, repo: str, path: str) -> str | None: ...
    def compare(self, repo: str, base: str, head: str) -> dict: ...


def load_watch_config(path: Path = DEFAULT_CONFIG_PATH) -> WatchConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceError(f"Cannot read {path}: {exc}") from exc
    repos = raw.get("repos") if isinstance(raw, dict) else None
    if not isinstance(repos, list) or not repos:
        raise SourceError(f"{path}: 'repos' must be a non-empty list")
    for repo in repos:
        if not isinstance(repo, str) or not REPO_PATTERN.match(repo):
            raise SourceError(f"{path}: invalid repo {repo!r} (expected owner/name)")
    interval = raw.get("update_interval_days")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise SourceError(f"{path}: 'update_interval_days' must be a positive integer")
    return WatchConfig(repos=list(repos), update_interval_days=interval)


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n[... README truncado ...]"


def language_shares(byte_counts: dict[str, int]) -> list[str]:
    """{'Python': 900, 'HTML': 100} -> ['Python 90%', 'HTML 10%'] (largest first)."""
    total = sum(byte_counts.values())
    if not total:
        return []
    ranked = sorted(byte_counts.items(), key=lambda item: -item[1])
    return [f"{name} {max(1, round(100 * count / total))}%" for name, count in ranked]


def read_readme(reader: RepoReader, repo: str) -> str:
    for path in SPANISH_README_PATHS:
        text = reader.get_file(repo, path)
        if text and text.strip():
            return text
    return reader.get_readme(repo) or ""


def take_snapshot(reader: RepoReader, repo: str) -> ProjectSnapshot:
    info = reader.get_repository(repo)
    return ProjectSnapshot(
        repo=repo,
        url=info["html_url"],
        description=(info.get("description") or "").strip(),
        languages=language_shares(reader.get_languages(repo)),
        readme=truncate(read_readme(reader, repo), MAX_README_CHARS),
        head_sha=reader.head_sha(repo, info["default_branch"]),
    )


def read_activity(reader: RepoReader, repo: str, base_sha: str, head_sha: str) -> ProjectActivity:
    """Commits and changed files between two commits of `repo`.

    Returns an activity with no commits if `base_sha` is not an ancestor of `head_sha`
    (e.g. rewritten history); the caller decides what to do.
    """
    data = reader.compare(repo, base_sha, head_sha)
    if data.get("status") not in ("ahead", "identical"):
        return ProjectActivity(base_sha=base_sha, head_sha=head_sha)
    commits = [
        f"{c['sha'][:7]} {c['commit']['message'].splitlines()[0].strip()}"
        for c in data.get("commits", [])
    ]
    files = [f"{f['status']} {f['filename']}" for f in data.get("files", [])]
    return ProjectActivity(
        base_sha=base_sha,
        head_sha=head_sha,
        commits=commits[-MAX_COMMITS:],
        files=files[:MAX_FILES],
        total_commits=int(data.get("total_commits", len(commits))),
    )
