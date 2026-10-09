from datetime import UTC, datetime
from pathlib import Path

import pytest

from linkedin_bot.generator.prompt import VoiceProfile
from linkedin_bot.generator.run import find_ideas, run_generator
from linkedin_bot.llm.base import LLMError
from linkedin_bot.store.posts import PUBLISHED, QUEUED, Post, PostStore, parse_post

NOW = datetime(2026, 10, 8, 7, 41, 5, 123, tzinfo=UTC)
PROFILE = VoiceProfile(rules="- Tono directo.", examples=["a", "b", "c"])


class FakeGit:
    def __init__(self, existing_branches=()):
        self.existing = set(existing_branches)
        self.pushed: dict[str, dict[Path, str]] = {}

    def remote_branch_exists(self, branch):
        return branch in self.existing

    def push_new_branch(self, branch, files, message):
        self.pushed[branch] = files
        self.existing.add(branch)


class FakeGitHub:
    def __init__(self, prs_by_branch=None):
        self.prs_by_branch = prs_by_branch or {}
        self.created: list[dict] = []

    def pull_requests_for_branch(self, branch):
        return self.prs_by_branch.get(branch, [])

    def create_pull_request(self, head, base, title, body):
        pull = {"number": 10 + len(self.created), "html_url": "u", "head": head,
                "base": base, "title": title, "body": body, "state": "open"}
        self.created.append(pull)
        self.prs_by_branch[head] = [pull]
        return pull


class FakeLLM:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.prompts: list[str] = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        if self.fail_on and self.fail_on in prompt:
            raise LLMError("rate limited")
        return f"Borrador sobre: {prompt.split('<material>')[1].split('</material>')[0].strip()}"


@pytest.fixture
def workspace(tmp_path):
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    return ideas, PostStore(tmp_path / "content")


def write_idea(ideas: Path, slug: str, text: str) -> Path:
    path = ideas / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run(workspace, git=None, github=None, llm=None, max_drafts=3):
    ideas, store = workspace
    git, github, llm = git or FakeGit(), github or FakeGitHub(), llm or FakeLLM()
    logs: list[str] = []
    code = run_generator(ideas, store, git, github, llm, PROFILE,
                         clock=lambda: NOW, log=logs.append, max_drafts=max_drafts)
    return code, git, github, llm, logs


def test_new_note_becomes_branch_with_queue_file_and_pr(workspace):
    ideas, store = workspace
    write_idea(ideas, "groq-switch", "Cambié a Groq.")

    code, git, github, _, _ = run(workspace)

    assert code == 0
    [(path, content)] = git.pushed["post/idea-groq-switch"].items()
    assert path == store.queue_path("2026-10-08-groq-switch")
    post = parse_post(content)
    assert post.status == QUEUED and post.source == "note"
    assert post.source_ref == (ideas / "groq-switch.md").as_posix()
    assert post.body == "Borrador sobre: Cambié a Groq."
    assert post.created_at == NOW.replace(microsecond=0)
    [pull] = github.created
    assert pull["head"] == "post/idea-groq-switch" and pull["base"] == "main"
    assert "Cambié a Groq." in pull["body"] and "2026-10-08-groq-switch" in pull["body"]


def test_second_run_opens_nothing(workspace):
    ideas, _ = workspace
    write_idea(ideas, "groq-switch", "Cambié a Groq.")
    git, github = FakeGit(), FakeGitHub()
    run(workspace, git=git, github=github)

    code, _, _, llm, logs = run(workspace, git=git, github=github)
    assert code == 0 and llm.prompts == [] and len(github.created) == 1
    assert any("skipping" in line for line in logs)


@pytest.mark.parametrize("state", ["closed", "open"])
def test_existing_pr_in_any_state_skips_note(workspace, state):
    ideas, _ = workspace
    write_idea(ideas, "rejected", "Nota.")
    github = FakeGitHub({"post/idea-rejected": [{"number": 3, "state": state}]})
    code, git, _, llm, _ = run(workspace, github=github)
    assert code == 0 and llm.prompts == [] and git.pushed == {}


def test_note_already_cited_by_a_post_is_skipped(workspace):
    ideas, store = workspace
    path = write_idea(ideas, "old", "Nota vieja.")
    store.published_dir.mkdir(parents=True)
    store._write(store.published_path("2026-10-01-old"), Post(
        id="2026-10-01-old", source="note", source_ref=path.as_posix(), status=PUBLISHED,
        created_at=NOW, body="x", linkedin_urn="urn:li:share:1", published_at=NOW,
    ))
    _, _, github, llm, _ = run(workspace)
    assert llm.prompts == [] and github.created == []


def test_branch_without_pr_only_opens_the_pr(workspace):
    ideas, _ = workspace
    write_idea(ideas, "half-done", "Nota.")
    git = FakeGit(existing_branches={"post/idea-half-done"})
    code, _, github, llm, _ = run(workspace, git=git)
    assert code == 0 and llm.prompts == [] and git.pushed == {}
    assert [p["head"] for p in github.created] == ["post/idea-half-done"]


def test_llm_failure_is_reported_and_other_notes_continue(workspace):
    ideas, _ = workspace
    write_idea(ideas, "a-fails", "FALLA")
    write_idea(ideas, "b-works", "Funciona.")
    code, git, github, _, logs = run(workspace, llm=FakeLLM(fail_on="FALLA"))
    assert code == 1
    assert list(git.pushed) == ["post/idea-b-works"]
    assert len(github.created) == 1
    assert any("draft FAILED" in line for line in logs)


def test_per_run_limit(workspace):
    ideas, _ = workspace
    for slug in ("n1", "n2", "n3"):
        write_idea(ideas, slug, f"Nota {slug}.")
    code, git, _, _, logs = run(workspace, max_drafts=2)
    assert code == 0 and list(git.pushed) == ["post/idea-n1", "post/idea-n2"]
    assert any("Reached 2 drafts" in line for line in logs)


def test_find_ideas_skips_bad_names_and_empty_notes(tmp_path):
    write_idea(tmp_path, "Bad Name", "x")
    write_idea(tmp_path, "empty", "   ")
    write_idea(tmp_path, "good-one", "Texto")
    (tmp_path / ".gitkeep").write_text("")
    logs: list[str] = []
    assert [i.slug for i in find_ideas(tmp_path, logs.append)] == ["good-one"]
    assert len(logs) == 2


def test_missing_ideas_dir_means_nothing_to_do(tmp_path):
    assert find_ideas(tmp_path / "nope") == []
