from datetime import UTC, datetime, timedelta

import pytest

from linkedin_bot.ops.token_reminder import (
    ISSUE_MARKER,
    TokenConfig,
    TokenConfigError,
    evaluate,
    load_token_config,
    run_reminder,
    write_token_expiry,
)

EXPIRES = datetime(2026, 12, 6, 12, 52, tzinfo=UTC)
CONFIG = TokenConfig(expires_at=EXPIRES, remind_days_before=14)


class FakeIssues:
    def __init__(self, open_issues=None):
        self.open = list(open_issues or [])
        self.created = []

    def list_open_issues(self):
        return self.open

    def create_issue(self, title, body):
        issue = {"number": 40 + len(self.created), "title": title, "body": body,
                 "html_url": "u"}
        self.created.append(issue)
        return issue


def test_repo_config_file_is_valid():
    config = load_token_config()
    assert config.expires_at == EXPIRES
    assert config.remind_days_before == 14


def test_no_reminder_outside_the_window():
    assert evaluate(CONFIG, EXPIRES - timedelta(days=14)) is None
    assert evaluate(CONFIG, datetime(2026, 10, 12, tzinfo=UTC)) is None


def test_reminder_inside_the_window():
    reminder = evaluate(CONFIG, EXPIRES - timedelta(days=13, hours=23))
    assert reminder is not None and not reminder.expired
    assert reminder.title.startswith(ISSUE_MARKER)
    assert "2026-12-06 12:52 UTC" in reminder.title and "13 days left" in reminder.title
    assert "uv run linkedin-bot-auth" in reminder.body
    assert "LINKEDIN_ACCESS_TOKEN" in reminder.body


def test_expired_reminder():
    reminder = evaluate(CONFIG, EXPIRES + timedelta(minutes=1))
    assert reminder.expired and "EXPIRED" in reminder.title


def test_run_opens_one_issue_inside_window():
    issues = FakeIssues()
    logs = []
    code = run_reminder(CONFIG, issues, datetime(2026, 11, 25, tzinfo=UTC), logs.append)
    assert code == 0
    assert len(issues.created) == 1
    assert "Opened reminder issue #40" in logs[0]


def test_run_does_not_duplicate_an_open_reminder():
    existing = {"number": 7, "title": f"{ISSUE_MARKER} LinkedIn token expires on ..."}
    issues = FakeIssues([existing, {"number": 8, "title": "Unrelated"}])
    logs = []
    run_reminder(CONFIG, issues, datetime(2026, 11, 30, tzinfo=UTC), logs.append)
    assert issues.created == []
    assert "#7 is already open" in logs[0]


def test_run_outside_window_does_nothing():
    issues = FakeIssues()
    logs = []
    assert run_reminder(CONFIG, issues, datetime(2026, 10, 12, tzinfo=UTC), logs.append) == 0
    assert issues.created == [] and "No reminder" in logs[0]


def test_run_fails_when_expired():
    issues = FakeIssues()
    assert run_reminder(CONFIG, issues, EXPIRES + timedelta(days=1), lambda _: None) == 1
    assert len(issues.created) == 1


def test_write_token_expiry_keeps_window_and_roundtrips(tmp_path):
    path = tmp_path / "linkedin_token.yml"
    path.write_text('expires_at: "2026-01-01T00:00:00+00:00"\nremind_days_before: 10\n',
                    encoding="utf-8")
    new_expiry = datetime(2027, 2, 4, 12, 52, 31, 999, tzinfo=UTC)
    write_token_expiry(new_expiry, path)
    config = load_token_config(path)
    assert config.expires_at == datetime(2027, 2, 4, 12, 52, tzinfo=UTC)
    assert config.remind_days_before == 10
    assert "linkedin-bot-auth" in path.read_text(encoding="utf-8")


def test_write_token_expiry_creates_missing_file(tmp_path):
    path = tmp_path / "config" / "linkedin_token.yml"
    write_token_expiry(EXPIRES, path)
    assert load_token_config(path) == CONFIG


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("remind_days_before: 14\n", "expires_at"),
        ('expires_at: "soon"\n', "invalid ISO"),
        ('expires_at: "2026-12-06T12:52:00+00:00"\nremind_days_before: 0\n', "positive"),
    ],
)
def test_invalid_token_config(tmp_path, content, message):
    path = tmp_path / "t.yml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TokenConfigError, match=message):
        load_token_config(path)
