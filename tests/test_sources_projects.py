import pytest

from linkedin_bot.sources.projects import (
    MAX_README_CHARS,
    SourceError,
    load_watch_config,
    read_activity,
    take_snapshot,
    truncate,
)


class FakeReader:
    def __init__(self, compare_status="ahead"):
        self.compare_status = compare_status
        self.compared = []

    def get_repository(self, repo):
        return {"html_url": f"https://github.com/{repo}", "description": " Desc ",
                "default_branch": "master"}

    def get_languages(self, repo):
        return {"HTML": 10, "Python": 500, "Mako": 1}

    def head_sha(self, repo, branch):
        assert branch == "master"
        return "a" * 40

    def get_readme(self, repo):
        return "# Title\n" + "x" * (MAX_README_CHARS + 100)

    def compare(self, repo, base, head):
        self.compared.append((repo, base, head))
        return {
            "status": self.compare_status,
            "total_commits": 2,
            "commits": [
                {"sha": "1111111aaaa", "commit": {"message": "cambios\n\nbody"}},
                {"sha": "2222222bbbb", "commit": {"message": "Add knowledge base"}},
            ],
            "files": [{"status": "added", "filename": "app/kb.py"},
                      {"status": "modified", "filename": "README.md"}],
        }


def test_load_repo_config_file_is_valid():
    config = load_watch_config()
    assert config.update_interval_days == 7
    assert "RevxngeDev/trade-sentinel" in config.repos


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("update_interval_days: 7\nrepos: []\n", "non-empty"),
        ("update_interval_days: 7\nrepos: [not a repo]\n", "invalid repo"),
        ("update_interval_days: 0\nrepos: [o/r]\n", "positive"),
        ("repos: [o/r]\n", "positive"),
    ],
)
def test_invalid_watch_config(tmp_path, content, message):
    path = tmp_path / "w.yml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SourceError, match=message):
        load_watch_config(path)


def test_snapshot_collects_metadata_sorted_languages_and_truncated_readme():
    snap = take_snapshot(FakeReader(), "o/repo")
    assert snap.url == "https://github.com/o/repo"
    assert snap.description == "Desc"
    assert snap.languages == ["Python", "HTML", "Mako"]
    assert snap.head_sha == "a" * 40
    assert snap.readme.endswith("[... README truncado ...]")
    assert len(snap.readme) <= MAX_README_CHARS + 40


def test_truncate_keeps_short_text():
    assert truncate("  corto  ", 100) == "corto"


def test_activity_lists_commits_and_files():
    reader = FakeReader()
    activity = read_activity(reader, "o/r", "base", "head")
    assert reader.compared == [("o/r", "base", "head")]
    assert activity.commits == ["1111111 cambios", "2222222 Add knowledge base"]
    assert activity.files == ["added app/kb.py", "modified README.md"]
    assert activity.total_commits == 2


def test_diverged_history_returns_no_commits():
    activity = read_activity(FakeReader(compare_status="diverged"), "o/r", "b", "h")
    assert activity.commits == [] and activity.files == []
