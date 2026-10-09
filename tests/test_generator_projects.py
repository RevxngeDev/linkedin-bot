from datetime import UTC, datetime, timedelta

import pytest

from linkedin_bot.generator.projects import (
    INTRO,
    UPDATE,
    branch_name,
    plan_repo,
    repo_slug,
    run_projects,
)
from linkedin_bot.generator.prompt import VoiceProfile
from linkedin_bot.llm.base import LLMError
from linkedin_bot.sources.projects import WatchConfig
from linkedin_bot.store.posts import PUBLISHED, Post, PostStore, parse_post

NOW = datetime(2026, 10, 9, 7, 41, tzinfo=UTC)
WEEK = timedelta(days=7)
REPO = "RevxngeDev/trade-sentinel"
SHA_OLD = "1" * 40
SHA_HEAD = "2" * 40
PROFILE = VoiceProfile(rules="- Tono.", examples=["a", "b", "c"])


def pr(kind, sha, created, state="closed", number=5, repo=REPO):
    return {"number": number, "state": state, "created_at": created.isoformat(),
            "head": {"ref": branch_name(repo, kind, sha)}}


def test_slug_and_branch_names():
    assert repo_slug("RevxngeDev/trade-sentinel") == "trade-sentinel"
    assert repo_slug("RevxngeDev/AgroChat") == "agrochat"
    assert repo_slug("o/My_Repo.v2") == "my-repo-v2"
    assert branch_name(REPO, INTRO, SHA_HEAD) == f"post/project-trade-sentinel-intro-{SHA_HEAD}"


def test_first_time_drafts_intro():
    assert plan_repo(REPO, SHA_HEAD, [], [], NOW, WEEK).action == INTRO


def test_open_pr_waits():
    plan = plan_repo(REPO, SHA_HEAD, [pr(INTRO, SHA_OLD, NOW, state="open")], [], NOW, WEEK)
    assert plan.action == "wait" and "#5" in plan.reason


def test_closed_intro_counts_as_done_and_respects_interval():
    pulls = [pr(INTRO, SHA_OLD, NOW - timedelta(days=3))]
    assert plan_repo(REPO, SHA_HEAD, pulls, [], NOW, WEEK).action == "wait"


def test_update_after_interval_with_new_commits():
    pulls = [pr(INTRO, SHA_OLD, NOW - timedelta(days=8))]
    plan = plan_repo(REPO, SHA_HEAD, pulls, [], NOW, WEEK)
    assert plan.action == UPDATE and plan.base_sha == SHA_OLD


def test_nothing_when_head_already_covered():
    pulls = [pr(INTRO, SHA_HEAD, NOW - timedelta(days=30))]
    assert plan_repo(REPO, SHA_HEAD, pulls, [], NOW, WEEK).action == "nothing"


def test_latest_draft_defines_covered_commit():
    pulls = [
        pr(INTRO, SHA_OLD, NOW - timedelta(days=30)),
        pr(UPDATE, "3" * 40, NOW - timedelta(days=10)),
    ]
    assert plan_repo(REPO, SHA_HEAD, pulls, [], NOW, WEEK).base_sha == "3" * 40


def test_published_post_counts_as_history():
    post = Post(id="2026-10-01-trade-sentinel-intro", source="project_intro",
                source_ref=f"{REPO}@{SHA_HEAD}", status=PUBLISHED,
                created_at=NOW - timedelta(days=20), body="x",
                linkedin_urn="urn:li:share:1", published_at=NOW)
    assert plan_repo(REPO, SHA_HEAD, [], [post], NOW, WEEK).action == "nothing"


def test_other_repos_and_note_branches_are_ignored():
    pulls = [pr(INTRO, SHA_OLD, NOW, state="open", repo="RevxngeDev/AgroChat"),
             {"number": 2, "state": "open", "created_at": NOW.isoformat(),
              "head": {"ref": "post/idea-trade-sentinel"}}]
    assert plan_repo(REPO, SHA_HEAD, pulls, [], NOW, WEEK).action == INTRO


# --- run_projects with fakes -------------------------------------------------------


class FakeGitHub:
    def __init__(self, pulls=None, broken_repos=()):
        self.pulls = list(pulls or [])
        self.broken = set(broken_repos)
        self.created = []

    def list_pull_requests(self):
        return self.pulls

    def create_pull_request(self, head, base, title, body):
        pull = {"number": 20 + len(self.created), "html_url": "u", "head": {"ref": head},
                "state": "open", "title": title, "body": body,
                "created_at": NOW.isoformat()}
        self.created.append(pull)
        return pull

    def get_repository(self, repo):
        if repo in self.broken:
            raise RuntimeError("404")
        return {"html_url": f"https://github.com/{repo}", "description": "D",
                "default_branch": "main"}

    def get_languages(self, repo):
        return {"Python": 1}

    def head_sha(self, repo, branch):
        return SHA_HEAD

    def get_readme(self, repo):
        return f"README de {repo}"

    def get_file(self, repo, path):
        return None

    def compare(self, repo, base, head):
        return {"status": "ahead", "total_commits": 1,
                "commits": [{"sha": "abcdef12", "commit": {"message": "fixed"}}],
                "files": [{"status": "added", "filename": "app/x.py"}]}


class FakeGit:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.pushed = {}

    def remote_branch_exists(self, branch):
        return branch in self.existing

    def push_new_branch(self, branch, files, message):
        self.pushed[branch] = files


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("429")
        return "Post del proyecto #Python"


def run(tmp_path, repos=(REPO,), github=None, git=None, llm=None, max_drafts=3,
        checker=None):
    config = WatchConfig(repos=list(repos), update_interval_days=7)
    github, git, llm = github or FakeGitHub(), git or FakeGit(), llm or FakeLLM()
    logs = []
    code = run_projects(config, PostStore(tmp_path), git, github, llm, PROFILE,
                        clock=lambda: NOW, log=logs.append, max_drafts=max_drafts,
                        checker=checker)
    return code, github, git, llm, logs


def test_intro_run_pushes_branch_and_opens_pr(tmp_path):
    code, github, git, llm, _ = run(tmp_path)
    branch = branch_name(REPO, INTRO, SHA_HEAD)
    assert code == 0
    [(path, content)] = git.pushed[branch].items()
    post = parse_post(content)
    assert path.name == "2026-10-09-trade-sentinel-intro.md"
    assert post.source == "project_intro"
    assert post.source_ref == f"{REPO}@{SHA_HEAD}"
    assert "PRESENTACIÓN" in llm.prompts[0] and "README de" in llm.prompts[0]
    assert github.created[0]["head"]["ref"] == branch


def test_update_run_uses_compare_material(tmp_path):
    github = FakeGitHub(pulls=[pr(INTRO, SHA_OLD, NOW - timedelta(days=8))])
    code, _, git, llm, _ = run(tmp_path, github=github)
    assert code == 0
    assert list(git.pushed) == [branch_name(REPO, UPDATE, SHA_HEAD)]
    assert "ACTUALIZACIÓN" in llm.prompts[0]
    assert "abcdef1 fixed" in llm.prompts[0] and "added app/x.py" in llm.prompts[0]


def test_waiting_repo_does_nothing(tmp_path):
    github = FakeGitHub(pulls=[pr(INTRO, SHA_OLD, NOW, state="open")])
    code, _, git, llm, logs = run(tmp_path, github=github)
    assert code == 0 and git.pushed == {} and llm.prompts == []
    assert any("skipping" in line for line in logs)


def test_existing_branch_only_opens_pr(tmp_path):
    git = FakeGit(existing={branch_name(REPO, INTRO, SHA_HEAD)})
    _, github, _, llm, _ = run(tmp_path, git=git)
    assert llm.prompts == [] and git.pushed == {} and len(github.created) == 1


def test_failures_are_isolated_per_repo(tmp_path):
    repos = ("RevxngeDev/broken", REPO)
    code, github, git, _, logs = run(tmp_path, repos=repos,
                                     github=FakeGitHub(broken_repos={"RevxngeDev/broken"}))
    assert code == 1 and len(github.created) == 1
    assert any("cannot read repo data" in line for line in logs)


def test_llm_failure_reports_and_opens_nothing(tmp_path):
    code, github, git, _, _ = run(tmp_path, llm=FakeLLM(fail=True))
    assert code == 1 and github.created == [] and git.pushed == {}


@pytest.mark.parametrize("limit", [1, 2])
def test_per_run_limit(tmp_path, limit):
    repos = ("o/a", "o/b", "o/c")
    _, github, _, _, _ = run(tmp_path, repos=repos, max_drafts=limit)
    assert len(github.created) == limit


class FakeChecker:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, system, prompt):
        self.calls.append((system, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_fact_check_report_goes_into_pr_body(tmp_path):
    checker = FakeChecker("- «CLI en JavaScript» → el README no menciona ninguna CLI web")
    _, github, _, _, _ = run(tmp_path, checker=checker)
    [(system, prompt)] = checker.calls
    assert "verificador" in system
    assert "<borrador>\nPost del proyecto #Python\n</borrador>" in prompt
    assert "README de" in prompt
    assert "CLI en JavaScript" in github.created[0]["body"]


def test_clean_fact_check_is_reported_as_no_problems(tmp_path):
    _, github, _, _, _ = run(tmp_path, checker=FakeChecker("SIN PROBLEMAS"))
    assert "No problems detected" in github.created[0]["body"]


def test_failed_fact_check_does_not_block_the_pr(tmp_path):
    _, github, _, _, _ = run(tmp_path, checker=FakeChecker(LLMError("429")))
    assert len(github.created) == 1
    assert "could not run" in github.created[0]["body"]
