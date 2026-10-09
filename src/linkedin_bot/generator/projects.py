"""Turn activity in watched repos into draft PRs (Phase 3, D-018, D-029).

Per repo, in order:
  1. An open project PR for the repo → wait for the owner.
  2. No intro yet (no intro PR in any state, no intro post) → draft an INTRODUCTION.
  3. Last project draft newer than `update_interval_days` → wait.
  4. HEAD already covered by the last draft → nothing new.
  5. Otherwise → draft one UPDATE summarising everything since the covered commit.
The covered commit is encoded in branch names (`post/project-<repo>-intro-<sha>`,
`post/project-<repo>-update-<sha>`) and in posts' `source_ref` (`<owner>/<repo>@<sha>`),
so no state file is needed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from linkedin_bot.generator.draft import check_draft, write_draft
from linkedin_bot.generator.prompt import (
    GeneratorError,
    VoiceProfile,
    build_project_intro_prompt,
    build_project_update_prompt,
)
from linkedin_bot.llm.base import LLMClient, LLMError
from linkedin_bot.sources.projects import (
    ProjectSnapshot,
    RepoReader,
    WatchConfig,
    read_activity,
    take_snapshot,
)
from linkedin_bot.store.posts import QUEUED, Post, PostStore, render_post

BASE_BRANCH = "main"
INTRO = "intro"
UPDATE = "update"
SOURCES = {INTRO: "project_intro", UPDATE: "project_update"}
MAX_PROJECT_DRAFTS_PER_RUN = 3


class GitPort(Protocol):
    def remote_branch_exists(self, branch: str) -> bool: ...
    def push_new_branch(self, branch: str, files: dict[Path, str], message: str) -> None: ...


class GitHubPort(RepoReader, Protocol):
    def list_pull_requests(self) -> list[dict]: ...
    def create_pull_request(self, head: str, base: str, title: str, body: str) -> dict: ...


@dataclass(frozen=True)
class Covered:
    """The latest project draft for a repo: which commit it covered and when."""

    kind: str
    sha: str
    at: datetime


@dataclass(frozen=True)
class Plan:
    action: str  # "intro" | "update" | "wait" | "nothing"
    reason: str
    base_sha: str | None = None


def repo_slug(repo: str) -> str:
    """'RevxngeDev/trade-sentinel' -> 'trade-sentinel' (lowercase, [a-z0-9-] only)."""
    name = repo.split("/", 1)[1].lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def branch_prefix(repo: str) -> str:
    return f"post/project-{repo_slug(repo)}-"


def branch_name(repo: str, kind: str, sha: str) -> str:
    return f"{branch_prefix(repo)}{kind}-{sha}"


def _parse_branch(repo: str, ref: str) -> tuple[str, str] | None:
    match = re.fullmatch(re.escape(branch_prefix(repo)) + r"(intro|update)-([0-9a-f]{40})", ref)
    return (match.group(1), match.group(2)) if match else None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def plan_repo(
    repo: str,
    head_sha: str,
    pulls: list[dict],
    posts: list[Post],
    now: datetime,
    interval: timedelta,
) -> Plan:
    history: list[Covered] = []
    open_pulls = []
    for pull in pulls:
        parsed = _parse_branch(repo, pull.get("head", {}).get("ref", ""))
        if not parsed:
            continue
        history.append(Covered(parsed[0], parsed[1], _parse_time(pull["created_at"])))
        if pull.get("state") == "open":
            open_pulls.append(pull)
    for post in posts:
        if post.source in SOURCES.values() and post.source_ref.startswith(f"{repo}@"):
            kind = INTRO if post.source == SOURCES[INTRO] else UPDATE
            history.append(Covered(kind, post.source_ref.split("@", 1)[1], post.created_at))

    if open_pulls:
        return Plan("wait", f"PR #{open_pulls[0]['number']} is still open")
    if not any(c.kind == INTRO for c in history):
        return Plan(INTRO, "no introduction yet")

    latest = max(history, key=lambda c: c.at)
    if now - latest.at < interval:
        return Plan("wait", f"last draft on {latest.at:%Y-%m-%d}; interval not reached")
    if head_sha == latest.sha:
        return Plan("nothing", "no new commits since the last draft")
    return Plan(UPDATE, f"new commits since {latest.sha[:7]}", base_sha=latest.sha)


NO_CHECK = "Not available: the draft was written in an earlier run."


def pull_request_body(
    snapshot: ProjectSnapshot, kind: str, post_id: str, details: str, fact_check: str = NO_CHECK
) -> str:
    title = "Introduction" if kind == INTRO else "Update"
    return f"""{title} draft generated from the public repo [{snapshot.repo}]({snapshot.url}).

**Automatic fact check** (second AI pass; it flags, it does not edit)

{fact_check}

**Review checklist**
- [ ] Every fact in the draft comes from the repo data below (nothing invented).
- [ ] It sounds like me; edit the file in this PR as much as needed.
- [ ] Hashtags and the repo link are right.

**Merge** = approve: `publish.yml` publishes it (max 1 post per UTC day).
**Close** = reject: the next draft for this repo waits for the weekly interval.

<details><summary>Source data</summary>

{details}

</details>

Post file: `content/queue/{post_id}.md`
"""


def run_projects(
    config: WatchConfig,
    store: PostStore,
    git: GitPort,
    github: GitHubPort,
    llm: LLMClient,
    profile: VoiceProfile,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    log: Callable[[str], None] = print,
    max_drafts: int = MAX_PROJECT_DRAFTS_PER_RUN,
    checker: LLMClient | None = None,
) -> int:
    """Return a process exit code: 0 = all good, 1 = at least one repo failed."""
    posts = store.list_queue() + store.list_published()
    pulls = github.list_pull_requests()
    interval = timedelta(days=config.update_interval_days)
    opened = 0
    failures = 0

    for repo in config.repos:
        if opened >= max_drafts:
            log(f"Reached {max_drafts} project drafts this run; others wait for the next run.")
            break
        try:
            snapshot = take_snapshot(github, repo)
        except Exception as exc:  # noqa: BLE001 — one unreachable repo must not stop the rest
            log(f"{repo}: cannot read repo data: {exc}")
            failures += 1
            continue

        plan = plan_repo(repo, snapshot.head_sha, pulls, posts, clock(), interval)
        if plan.action in ("wait", "nothing"):
            log(f"{repo}: {plan.reason}; skipping.")
            continue

        branch = branch_name(repo, plan.action, snapshot.head_sha)
        post_id = f"{clock():%Y-%m-%d}-{repo_slug(repo)}-{plan.action}"
        details = f"Commit covered: `{snapshot.head_sha}`"
        fact_check = NO_CHECK
        if not git.remote_branch_exists(branch):
            try:
                if plan.action == INTRO:
                    prompt = build_project_intro_prompt(snapshot)
                else:
                    activity = read_activity(github, repo, plan.base_sha, snapshot.head_sha)
                    if not activity.commits:
                        log(f"{repo}: history between {plan.base_sha[:7]} and HEAD is not "
                            "linear (rewritten?); skipping, needs a manual look.")
                        failures += 1
                        continue
                    details += "\n\nCommits:\n" + "\n".join(f"- {c}" for c in activity.commits)
                    prompt = build_project_update_prompt(snapshot, activity)
                body = write_draft(llm, profile, prompt)
            except (LLMError, GeneratorError) as exc:
                log(f"{repo}: draft FAILED: {exc}")
                failures += 1
                continue
            if checker is not None:
                fact_check = check_draft(checker, prompt, body)
            post = Post(
                id=post_id,
                source=SOURCES[plan.action],
                source_ref=f"{repo}@{snapshot.head_sha}",
                status=QUEUED,
                created_at=clock().replace(microsecond=0),
                body=body,
            )
            git.push_new_branch(
                branch,
                {store.queue_path(post.id): render_post(post)},
                f"Draft {plan.action} post {post.id} from {repo}@{snapshot.head_sha[:7]}",
            )
        else:
            log(f"{repo}: branch {branch} exists without a PR; opening the PR only.")

        pull = github.create_pull_request(
            head=branch,
            base=BASE_BRANCH,
            title=f"Post draft: {repo_slug(repo)} {plan.action}",
            body=pull_request_body(snapshot, plan.action, post_id, details, fact_check),
        )
        log(f"{repo}: {plan.reason} → opened PR #{pull['number']} {pull.get('html_url', '')}")
        opened += 1

    log(f"Projects done: {opened} PR(s) opened, {failures} failure(s).")
    return 1 if failures else 0
