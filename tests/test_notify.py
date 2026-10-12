import json
from datetime import UTC, datetime, timedelta

import httpx

from linkedin_bot.notify import messages
from linkedin_bot.notify.telegram import (
    MAX_MESSAGE_CHARS,
    NullNotifier,
    TelegramNotifier,
    build_notifier,
    esc,
    fit,
)
from linkedin_bot.ops.telegram_check import list_recent_chats
from linkedin_bot.ops.token_reminder import TokenConfig
from linkedin_bot.ops.weekly_summary import build_summary
from linkedin_bot.store.posts import PUBLISHED, QUEUED, Post, PostStore

TOKEN = "123456:SECRET-token"


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=()):
        self.sent.append((text, list(buttons)))


def notifier_with(handler, logs=None):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramNotifier(http, TOKEN, "42", (logs if logs is not None else []).append)


# --- TelegramNotifier -----------------------------------------------------------------

def test_send_posts_html_message_with_url_buttons():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"ok": True, "result": {}})

    notifier_with(handler).send("<b>Hola</b>", [("📝 Revisar PR", "https://github.com/x/1")])
    request = seen["request"]
    body = json.loads(request.content)
    assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert body["chat_id"] == "42" and body["text"] == "<b>Hola</b>"
    assert body["parse_mode"] == "HTML"
    assert body["link_preview_options"] == {"is_disabled": True}
    assert body["reply_markup"] == {
        "inline_keyboard": [[{"text": "📝 Revisar PR", "url": "https://github.com/x/1"}]]
    }


def test_send_without_buttons_has_no_markup():
    def handler(request):
        assert "reply_markup" not in json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    notifier_with(handler).send("hola")


def test_api_error_is_logged_not_raised():
    logs = []
    notifier_with(lambda r: httpx.Response(400, json={"ok": False, "description": "chat not found"}),
                  logs).send("x")
    assert logs == ["Telegram notification failed: chat not found"]


def test_network_error_is_logged_without_the_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{TOKEN}/sendMessage")

    logs = []
    notifier_with(handler, logs).send("x")
    assert len(logs) == 1 and TOKEN not in logs[0] and "***" in logs[0]


def test_build_notifier_needs_both_secrets():
    with httpx.Client(trust_env=False) as http:
        assert isinstance(build_notifier(http, {}), NullNotifier)
        assert isinstance(build_notifier(http, {"TELEGRAM_BOT_TOKEN": "t"}), NullNotifier)
        both = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}
        assert isinstance(build_notifier(http, both), TelegramNotifier)


def test_escape_and_fit():
    assert esc('a <b> & "c"') == "a &lt;b&gt; &amp; &quot;c&quot;"
    long = "x" * (MAX_MESSAGE_CHARS + 50)
    assert len(fit(long)) == MAX_MESSAGE_CHARS and fit(long).endswith("…")


# --- messages --------------------------------------------------------------------------

def test_draft_message_escapes_content_and_links_the_pr():
    text, buttons = messages.draft_opened(
        "nota", "content/ideas/a.md", "Uso <script> & #Python", "SIN <problemas>",
        "https://github.com/o/r/pull/9", 9,
    )
    assert "&lt;script&gt; &amp; #Python" in text and "<script>" not in text
    assert "PR #9" in text
    assert buttons == [("📝 Revisar PR", "https://github.com/o/r/pull/9")]


def test_long_draft_still_fits_in_one_message():
    text, _ = messages.draft_opened("nota", "s", "palabra " * 2000, "c " * 2000, "u", 1)
    assert len(text) < MAX_MESSAGE_CHARS


def test_published_message_links_the_post():
    text, buttons = messages.published("2026-10-12-x", "urn:li:share:7", "Cuerpo")
    assert "Publicado" in text
    assert buttons == [("🔗 Ver en LinkedIn", "https://www.linkedin.com/feed/update/urn:li:share:7/")]


def test_problem_message_with_and_without_link():
    _, buttons = messages.problem("Título", "detalle")
    assert buttons == []
    text, buttons = messages.problem("A <b>", "d", ("🔍 Ver", "https://x"))
    assert "A &lt;b&gt;" in text and buttons == [("🔍 Ver", "https://x")]


# --- weekly summary ---------------------------------------------------------------------

def test_weekly_summary_counts_last_seven_days(tmp_path):
    now = datetime(2026, 10, 19, 8, tzinfo=UTC)
    store = PostStore(tmp_path)
    store.published_dir.mkdir(parents=True)

    def published(post_id, days_ago):
        at = now - timedelta(days=days_ago)
        post = Post(id=post_id, source="note", source_ref="x", status=PUBLISHED, created_at=at,
                    body="b", linkedin_urn=f"urn:li:share:{days_ago}", published_at=at)
        store._write(store.published_path(post_id), post)

    published("recent", 2)
    published("old", 10)
    store.save_to_queue(Post(id="waiting", source="note", source_ref="y", status=QUEUED,
                             created_at=now, body="b"))

    class Pulls:
        def list_pull_requests(self):
            return [{"number": 8, "title": "Post draft: z", "html_url": "https://pr/8", "state": "open"},
                    {"number": 7, "title": "old", "html_url": "u", "state": "closed"}]

    token = TokenConfig(expires_at=now + timedelta(days=48), remind_days_before=14)
    text, buttons = build_summary(store, Pulls(), token, now, "https://github.com/o/r")
    assert "últimos 7 días: <b>1</b>" in text and "recent" in text and "old" not in text
    assert "En cola para publicar: <b>1</b>" in text and "waiting" in text
    assert "revisión: <b>1</b>" in text and "#8 Post draft: z" in text
    assert "caduca en <b>48</b> días" in text
    assert buttons == [("📂 Abrir el repositorio", "https://github.com/o/r")]


# --- telegram check -----------------------------------------------------------------------

def test_list_recent_chats():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": 555, "first_name": "Camilo"}}},
            {"update_id": 2, "message": {"chat": {"id": 555, "first_name": "Camilo"}}},
            {"update_id": 3, "edited_message": {}},
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert list_recent_chats(http, TOKEN) == [(555, "Camilo")]


def telegram_api(routes):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=routes[method])
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_diagnose_reports_bot_and_chat(capsys):
    from linkedin_bot.ops.telegram_check import diagnose

    http = telegram_api({
        "getMe": {"ok": True, "result": {"id": 9, "username": "RevxngeLinkedinBot"}},
        "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        "getUpdates": {"ok": True, "result": [
            {"update_id": 1, "my_chat_member": {"chat": {"id": 777, "first_name": "Camilo"}}}]},
    })
    assert diagnose(http, TOKEN) == 0
    out = capsys.readouterr().out
    assert "@RevxngeLinkedinBot" in out and "chat_id=777" in out and TOKEN not in out


def test_diagnose_detects_webhook(capsys):
    from linkedin_bot.ops.telegram_check import diagnose

    http = telegram_api({
        "getMe": {"ok": True, "result": {"id": 9, "username": "b"}},
        "getWebhookInfo": {"ok": True, "result": {"url": "https://elsewhere/hook"}},
    })
    assert diagnose(http, TOKEN) == 1
    assert "webhook is set" in capsys.readouterr().out


def test_diagnose_without_messages_explains(capsys):
    from linkedin_bot.ops.telegram_check import diagnose

    http = telegram_api({
        "getMe": {"ok": True, "result": {"id": 9, "username": "b"}},
        "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        "getUpdates": {"ok": True, "result": []},
    })
    assert diagnose(http, TOKEN) == 1
    out = capsys.readouterr().out
    assert "Pending updates: 0" in out and "No chats found" in out
