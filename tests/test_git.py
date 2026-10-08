import subprocess
from pathlib import Path

import pytest

from linkedin_bot.repo.git import Git, GitError


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """A bare 'origin' plus two clones: `work` (the bot) and `other` (a concurrent user)."""
    origin = tmp_path / "origin.git"
    sh(tmp_path, "init", "--bare", "-b", "main", str(origin))
    clones = {}
    for name in ("work", "other"):
        path = tmp_path / name
        sh(tmp_path, "clone", str(origin), str(path))
        sh(path, "config", "user.name", "T")
        sh(path, "config", "user.email", "t@example.com")
        sh(path, "checkout", "-B", "main")
        clones[name] = path
    seed = clones["work"] / "README.md"
    seed.write_text("seed\n")
    sh(clones["work"], "add", ".")
    sh(clones["work"], "commit", "-m", "seed")
    sh(clones["work"], "push", "origin", "main")
    sh(clones["other"], "pull", "origin", "main")
    return origin, clones["work"], clones["other"]


def make_git(path):
    return Git(path, "main", "bot", "bot@example.com")


def test_commit_that_added_finds_adding_commit(repos):
    _, work, _ = repos
    post = work / "content" / "queue" / "p.md"
    post.parent.mkdir(parents=True)
    post.write_text("v1\n")
    sh(work, "add", ".")
    sh(work, "commit", "-m", "add post")
    added = sh(work, "rev-parse", "HEAD")
    post.write_text("v2\n")
    sh(work, "commit", "-am", "edit post")

    git = make_git(work)
    assert git.commit_that_added(Path("content/queue/p.md")) == added
    assert git.commit_that_added(Path("content/queue/missing.md")) is None


def test_commit_and_push_includes_deletions_and_uses_bot_identity(repos):
    origin, work, _ = repos
    queue = work / "content" / "queue" / "p.md"
    queue.parent.mkdir(parents=True)
    queue.write_text("x\n")
    sh(work, "add", ".")
    sh(work, "commit", "-m", "add")
    sh(work, "push", "origin", "main")

    queue.unlink()
    published = work / "content" / "published" / "p.md"
    published.parent.mkdir(parents=True)
    published.write_text("x\n")
    make_git(work).commit_and_push(
        [Path("content/queue/p.md"), Path("content/published/p.md")], "Publish p"
    )

    files = sh(origin, "ls-tree", "-r", "--name-only", "main")
    assert "content/published/p.md" in files
    assert "content/queue/p.md" not in files
    assert sh(origin, "log", "-1", "--format=%an <%ae> %s", "main") == (
        "bot <bot@example.com> Publish p"
    )


def test_push_rebases_over_concurrent_change(repos):
    origin, work, other = repos
    (other / "other.txt").write_text("concurrent\n")
    sh(other, "add", ".")
    sh(other, "commit", "-m", "concurrent")
    sh(other, "push", "origin", "main")

    (work / "mine.txt").write_text("mine\n")
    make_git(work).commit_and_push([Path("mine.txt")], "mine")

    files = sh(origin, "ls-tree", "-r", "--name-only", "main")
    assert "mine.txt" in files and "other.txt" in files


def test_git_failure_raises(repos):
    _, work, _ = repos
    with pytest.raises(GitError, match="commit"):
        make_git(work).commit_and_push([Path("README.md")], "nothing changed")


def test_push_new_branch_creates_remote_branch_and_leaves_main_clean(repos):
    origin, work, _ = repos
    git = make_git(work)
    assert git.remote_branch_exists("post/idea-x") is False

    git.push_new_branch(
        "post/idea-x", {Path("content/queue/2026-10-08-x.md"): "post\n"}, "Draft x"
    )

    assert git.remote_branch_exists("post/idea-x") is True
    files = sh(origin, "ls-tree", "-r", "--name-only", "post/idea-x")
    assert "content/queue/2026-10-08-x.md" in files
    assert "content/queue/2026-10-08-x.md" not in sh(origin, "ls-tree", "-r", "--name-only", "main")
    assert sh(work, "branch", "--show-current") == "main"
    assert not (work / "content" / "queue" / "2026-10-08-x.md").exists()
    assert sh(origin, "log", "-1", "--format=%an %s", "post/idea-x") == "bot Draft x"


def test_push_new_branch_starts_from_latest_remote_main(repos):
    origin, work, other = repos
    (other / "newer.txt").write_text("newer\n")
    sh(other, "add", ".")
    sh(other, "commit", "-m", "newer")
    sh(other, "push", "origin", "main")

    make_git(work).push_new_branch("post/idea-y", {Path("y.md"): "y\n"}, "Draft y")
    files = sh(origin, "ls-tree", "-r", "--name-only", "post/idea-y")
    assert "newer.txt" in files and "y.md" in files
