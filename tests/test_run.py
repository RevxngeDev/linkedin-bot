from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from linkedin_bot.publisher.linkedin_client import PublishError
from linkedin_bot.publisher.run import run_once
from linkedin_bot.store.posts import PUBLISHED, PUBLISHING, QUEUED, Post, PostStore

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
AUTHOR = "urn:li:person:me"


class FakeGit:
    def __init__(self, added_in="sha-added"):
        self.added_in = added_in
        self.commits: list[tuple[list[Path], str]] = []

    def commit_that_added(self, path):
        return self.added_in

    def commit_and_push(self, paths, message):
        self.commits.append((paths, message))


class FakeGitHub:
    def __init__(self, merged=True):
        self.merged = merged
        self.asked: list[str] = []

    def merged_pull_request(self, commit_sha, base_branch):
        self.asked.append(commit_sha)
        return {"number": 7, "html_url": "https://github.com/o/r/pull/7"} if self.merged else None


class FakeLinkedIn:
    def __init__(self, error=None):
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def create_text_post(self, author_urn, text):
        self.calls.append((author_urn, text))
        if self.error:
            raise self.error
        return "urn:li:share:999"


def queued_post(post_id="2026-10-08-first", body="Hola (mundo) #Python"):
    return Post(
        id=post_id, source="note", source_ref="x", status=QUEUED,
        created_at=NOW - timedelta(hours=3), body=body,
    )


@pytest.fixture
def store(tmp_path):
    store = PostStore(tmp_path)
    store.save_to_queue(queued_post())
    return store


def run(store, git=None, github=None, linkedin=None):
    git, github, linkedin = git or FakeGit(), github or FakeGitHub(), linkedin or FakeLinkedIn()
    logs: list[str] = []
    code = run_once(store, git, github, linkedin, AUTHOR, clock=lambda: NOW, log=logs.append)
    return code, git, github, linkedin, logs


def test_publishes_once_records_urn_and_moves_file(store):
    code, git, github, linkedin, logs = run(store)

    assert code == 0
    assert linkedin.calls == [(AUTHOR, "Hola \\(mundo\\) {hashtag|\\#|Python}")]
    assert github.asked == ["sha-added"]
    assert store.list_queue() == []
    [done] = store.list_published()
    assert done.status == PUBLISHED
    assert done.linkedin_urn == "urn:li:share:999"
    assert done.published_at == NOW
    assert [message for _, message in git.commits] == [
        "Claim post 2026-10-08-first for publishing",
        "Publish post 2026-10-08-first (urn:li:share:999)",
    ]
    assert "Published post URN: urn:li:share:999" in logs


def test_second_run_publishes_nothing(store):
    run(store)
    code, git, _, linkedin, logs = run(store)
    assert code == 0
    assert linkedin.calls == [] and git.commits == []
    assert logs == ["A post was already published today (2026-10-08 UTC)."]


def test_refuses_file_not_merged_through_pr(store):
    code, git, _, linkedin, logs = run(store, github=FakeGitHub(merged=False))
    assert code == 1
    assert linkedin.calls == [] and git.commits == []
    assert store.list_queue()[0].status == QUEUED
    assert any(line.startswith("REFUSED") for line in logs)


def test_refuses_file_with_unknown_origin(store):
    code, _, github, linkedin, _ = run(store, git=FakeGit(added_in=None))
    assert code == 1 and linkedin.calls == [] and github.asked == []


def test_rejected_by_linkedin_releases_claim(store):
    error = PublishError("Create post failed (422): bad", status_code=422)
    code, git, _, _, _ = run(store, linkedin=FakeLinkedIn(error))
    assert code == 1
    assert store.list_queue()[0].status == QUEUED
    assert store.list_queue()[0].claimed_at is None
    assert git.commits[-1][1] == "Release claim on post 2026-10-08-first (rejected)"


@pytest.mark.parametrize(
    "error",
    [
        PublishError("Create post failed (503): down", status_code=503),
        PublishError("LinkedIn returned 201 without an x-restli-id header.", status_code=201),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_ambiguous_failure_stays_claimed_and_blocks_next_runs(store, error):
    code, git, _, _, _ = run(store, linkedin=FakeLinkedIn(error))
    assert code == 1
    assert store.list_queue()[0].status == PUBLISHING
    assert len(git.commits) == 1  # only the claim

    code, _, _, linkedin, logs = run(store)
    assert code == 1 and linkedin.calls == []
    assert "stuck in 'publishing'" in logs[0]


def test_nothing_queued_is_success(tmp_path):
    code, _, _, linkedin, logs = run(PostStore(tmp_path))
    assert code == 0 and linkedin.calls == []
    assert logs == ["No queued post is due."]


def test_already_published_id_left_in_queue_is_never_republished(store):
    done = replace(
        queued_post(), status=PUBLISHED, linkedin_urn="urn:li:share:1",
        published_at=NOW - timedelta(days=2),
    )
    store.move_to_published(done)
    store.save_to_queue(queued_post())  # same id back in the queue
    code, _, _, linkedin, _ = run(store)
    assert code == 0 and linkedin.calls == []


def test_expired_token_gives_renewal_hint(store):
    error = PublishError("Create post failed (401): expired", status_code=401)
    code, _, _, _, logs = run(store, linkedin=FakeLinkedIn(error))
    assert code == 1
    assert store.list_queue()[0].status == QUEUED
    assert any("linkedin-bot-auth" in line for line in logs)


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=()):
        self.sent.append((text, list(buttons)))


def test_publish_success_notifies_with_linkedin_button(store):
    notifier = RecordingNotifier()
    run_once(store, FakeGit(), FakeGitHub(), FakeLinkedIn(), AUTHOR, clock=lambda: NOW,
             log=lambda _: None, notifier=notifier, run_url="https://run/1")
    [(text, buttons)] = notifier.sent
    assert "Publicado" in text
    assert buttons == [("🔗 Ver en LinkedIn", "https://www.linkedin.com/feed/update/urn:li:share:999/")]


def test_refused_post_notifies_problem_with_run_link(store):
    notifier = RecordingNotifier()
    run_once(store, FakeGit(), FakeGitHub(merged=False), FakeLinkedIn(), AUTHOR,
             clock=lambda: NOW, log=lambda _: None, notifier=notifier, run_url="https://run/1")
    [(text, buttons)] = notifier.sent
    assert "PR fusionado" in text and buttons == [("🔍 Ver la ejecución", "https://run/1")]


def test_expired_token_notifies_renewal(store):
    notifier = RecordingNotifier()
    error = PublishError("Create post failed (401): expired", status_code=401)
    run_once(store, FakeGit(), FakeGitHub(), FakeLinkedIn(error), AUTHOR, clock=lambda: NOW,
             log=lambda _: None, notifier=notifier)
    assert "token de LinkedIn" in notifier.sent[0][0]


def test_nothing_to_publish_sends_nothing(tmp_path):
    notifier = RecordingNotifier()
    run_once(PostStore(tmp_path), FakeGit(), FakeGitHub(), FakeLinkedIn(), AUTHOR,
             clock=lambda: NOW, log=lambda _: None, notifier=notifier)
    assert notifier.sent == []


def test_actions_run_url():
    from linkedin_bot.publisher.run import actions_run_url

    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r",
           "GITHUB_RUN_ID": "5"}
    assert actions_run_url(env) == "https://github.com/o/r/actions/runs/5"
    assert actions_run_url({}) is None
