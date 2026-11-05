import base64
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import yaml

from linkedin_bot.notify.telegram import inline_keyboard
from linkedin_bot.repo.github import GitHubClient, GitHubError
from linkedin_bot.store.posts import PUBLISHED, QUEUED, Post, parse_post, render_post
from linkedin_bot.telegram_bot.api import BotApi, TelegramError
from linkedin_bot.telegram_bot.commands import BotCommands, slugify
from linkedin_bot.telegram_bot.service import authorized, dispatch, run_forever

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
MOSCOW = ZoneInfo("Europe/Moscow")
TOKEN = "123:SECRET"
POST_PATH = "content/queue/2026-10-17-kakao-update.md"


def draft_post(**kw):
    return Post(id="2026-10-17-kakao-update", source="project_update", source_ref="o/Kakao@x",
                status=QUEUED, created_at=datetime(2026, 10, 17, tzinfo=UTC), body="Post", **kw)


class FakeRepo:
    def __init__(self):
        self.pulls = {
            8: {"number": 8, "state": "open", "merged_at": None, "title": "Post draft: kakao update",
                "html_url": "https://github.com/o/r/pull/8", "created_at": "2026-10-17T11:46:18Z",
                "head": {"ref": "post/project-kakao-update-abc"},
                "body": f"...\nPost file: `{POST_PATH}`\n"},
            3: {"number": 3, "state": "open", "merged_at": None, "title": "Human PR",
                "html_url": "https://github.com/o/r/pull/3", "head": {"ref": "feature/x"}, "body": ""},
        }
        self.files = {
            (POST_PATH, "post/project-kakao-update-abc"): (render_post(draft_post()), "sha-post"),
            ("config/watched_repos.yml", None): (
                "update_interval_days: 7\nrepos:\n  - RevxngeDev/Kakao\n  - RevxngeDev/AgroChat\n",
                "sha-watch"),
            ("config/linkedin_token.yml", None): (
                'expires_at: "2026-12-06T12:52:00+00:00"\nremind_days_before: 14\n', "sha-tok"),
        }
        self.dirs = {"content/queue": [], "content/published": [], "content/ideas": ["hola.md"]}
        self.merged, self.closed, self.writes = [], [], []
        self.repos = {"RevxngeDev/Gepeto": {"full_name": "RevxngeDev/Gepeto", "private": False},
                      "RevxngeDev/secret": {"full_name": "RevxngeDev/secret", "private": True}}

    def get_pull_request(self, number):
        if number not in self.pulls:
            raise GitHubError(f"GitHub GET /pulls/{number} failed (404)")
        return self.pulls[number]

    def merge_pull_request(self, number):
        self.merged.append(number)
        self.pulls[number]["state"] = "closed"
        return {}

    def close_pull_request(self, number):
        self.closed.append(number)
        return {}

    def list_pull_requests(self):
        return list(self.pulls.values())

    def read_file(self, path, ref=None):
        return self.files.get((path, ref))

    def list_dir(self, path, ref=None):
        return self.dirs.get(path, [])

    def write_file(self, path, text, message, sha=None, branch=None):
        self.writes.append({"path": path, "text": text, "message": message, "sha": sha,
                            "branch": branch})

    def get_repository(self, repo):
        if repo not in self.repos:
            raise GitHubError(f"GitHub GET /repos/{repo} failed (404)")
        return self.repos[repo]


class FakeChat:
    def __init__(self):
        self.sent, self.answers, self.buttons = [], [], []

    def send(self, text, buttons=()):
        self.sent.append((text, list(buttons)))

    def answer(self, callback_id, text=""):
        self.answers.append(text)

    def set_buttons(self, message_id, buttons):
        self.buttons.append((message_id, list(buttons)))


@pytest.fixture
def bot():
    repo, chat = FakeRepo(), FakeChat()
    return BotCommands(repo, chat, MOSCOW, clock=lambda: NOW, log=lambda _: None), repo, chat


# --- approve / reject buttons -----------------------------------------------------------

def test_approve_asks_for_confirmation_then_merges(bot):
    commands, repo, chat = bot
    commands.handle_callback("q1", "approve:8", 55)
    assert repo.merged == []
    assert [t for _, t in chat.buttons[-1][1]] == ["cb:approve!:8", "cb:cancel:8"]
    commands.handle_callback("q2", "approve!:8", 55)
    assert repo.merged == [8]
    assert chat.buttons[-1] == (55, [("📝 Ver PR", "https://github.com/o/r/pull/8")])
    assert "aprobado" in chat.sent[-1][0]


def test_reject_confirmed_closes_pr(bot):
    commands, repo, chat = bot
    commands.handle_callback("q1", "reject:8", 55)
    assert repo.closed == []
    commands.handle_callback("q2", "reject!:8", 55)
    assert repo.closed == [8] and "cerrado" in chat.sent[-1][0]


def test_cancel_restores_draft_buttons(bot):
    commands, _, chat = bot
    commands.handle_callback("q", "cancel:8", 55)
    assert [t for _, t in chat.buttons[-1][1]] == [
        "https://github.com/o/r/pull/8", "cb:approve:8", "cb:reject:8"]


def test_never_merges_a_non_draft_pr(bot):
    commands, repo, chat = bot
    commands.handle_callback("q", "approve!:3", 55)
    assert repo.merged == [] and "no es un borrador" in chat.answers[-1]


def test_already_merged_pr_is_reported(bot):
    commands, repo, chat = bot
    repo.pulls[8].update(state="closed", merged_at="2026-11-01T00:00:00Z")
    commands.handle_callback("q", "approve!:8", 55)
    assert repo.merged == [] and "ya estaba fusionado" in chat.answers[-1]


def test_github_error_is_reported_not_raised(bot):
    commands, _, chat = bot
    commands.handle_callback("q", "approve!:99", 55)
    assert "No pude completar" in chat.sent[-1][0]


def test_unknown_button(bot):
    commands, _, chat = bot
    commands.handle_callback("q", "garbage", 1)
    assert chat.answers == ["Botón no reconocido"]


# --- commands ----------------------------------------------------------------------------

def test_help_and_unknown_and_plain_text(bot):
    commands, _, chat = bot
    commands.handle_text("/start")
    assert "/pendientes" in chat.sent[-1][0] and "Europe/Moscow" in chat.sent[-1][0]
    commands.handle_text("/xyz")
    assert "No conozco /xyz" in chat.sent[-1][0]
    commands.handle_text("hola bot")
    assert "/nota" in chat.sent[-1][0]


def test_pending_lists_only_open_drafts_with_buttons(bot):
    commands, _, chat = bot
    commands.handle_text("/pendientes")
    assert "1 borrador" in chat.sent[0][0]
    text, buttons = chat.sent[1]
    assert "#8" in text and [t for _, t in buttons][1:] == ["cb:approve:8", "cb:reject:8"]


def test_note_creates_file_with_unique_slug(bot):
    commands, repo, chat = bot
    commands.handle_text("/nota Hola: terminé el panel de admin de AgroChat con React")
    [write] = repo.writes
    assert write["path"] == "content/ideas/hola-termine-el-panel-de-admin.md"
    assert write["text"] == "Hola: terminé el panel de admin de AgroChat con React\n"
    assert write["branch"] is None and write["sha"] is None
    commands.handle_text("/nota hola")
    assert repo.writes[-1]["path"] == "content/ideas/hola-2.md"
    commands.handle_text("/nota")
    assert "Escribe la nota" in chat.sent[-1][0]


def test_slugify():
    assert slugify("¡Añadí Ñandú y Café! 2026") == "anadi-nandu-y-cafe-2026"
    assert slugify("!!!") == "nota"


def test_schedule_sets_publish_at_in_utc_on_the_pr_branch(bot):
    commands, repo, chat = bot
    commands.handle_text("/programar 8 2026-11-10 09:00")
    [write] = repo.writes
    assert write["path"] == POST_PATH and write["branch"] == "post/project-kakao-update-abc"
    assert write["sha"] == "sha-post"
    assert parse_post(write["text"]).publish_at == datetime(2026, 11, 10, 6, tzinfo=UTC)
    assert "2026-11-10 09:00 (Europe/Moscow)" in chat.sent[-1][0]


def test_schedule_clear(bot):
    commands, repo, _ = bot
    commands.handle_text("/programar 8 quitar")
    assert parse_post(repo.writes[-1]["text"]).publish_at is None


@pytest.mark.parametrize(("args", "reply"), [
    ("", "Uso"), ("8 mañana", "no válidas"), ("8 2026-13-01 09:00", "no válidas"),
    ("8 2026-11-01 09:00", "ya pasó"), ("3 2026-11-10 09:00", "no es un borrador"),
])
def test_schedule_rejects_bad_input(bot, args, reply):
    commands, repo, chat = bot
    commands.handle_text(f"/programar {args}")
    assert repo.writes == [] and reply in chat.sent[-1][0]


def test_repos_list_add_remove(bot):
    commands, repo, chat = bot
    commands.handle_text("/repos")
    assert "RevxngeDev/Kakao" in chat.sent[-1][0]
    commands.handle_text("/repo_add RevxngeDev/Gepeto")
    written = yaml.safe_load(repo.writes[-1]["text"])
    assert written["repos"][-1] == "RevxngeDev/Gepeto" and written["update_interval_days"] == 7
    assert repo.writes[-1]["sha"] == "sha-watch"
    commands.handle_text("/repo_remove revxngedev/agrochat")
    assert yaml.safe_load(repo.writes[-1]["text"])["repos"] == ["RevxngeDev/Kakao"]


def test_repo_add_refuses_private_duplicate_and_bad_names(bot):
    commands, repo, chat = bot
    for args, reply in [("RevxngeDev/secret", "privado"), ("RevxngeDev/Kakao", "Ya vigilo"),
                        ("no-slash", "Uso")]:
        commands.handle_text(f"/repo_add {args}")
        assert reply in chat.sent[-1][0]
    assert repo.writes == []


def test_written_watch_config_stays_loadable(bot, tmp_path):
    from linkedin_bot.sources.projects import load_watch_config

    commands, repo, _ = bot
    commands.handle_text("/repo_add RevxngeDev/Gepeto")
    path = tmp_path / "w.yml"
    path.write_text(repo.writes[-1]["text"], encoding="utf-8")
    assert load_watch_config(path).repos[-1] == "RevxngeDev/Gepeto"


def test_queue_published_and_token(bot):
    commands, repo, chat = bot
    commands.handle_text("/cola")
    assert "vacía" in chat.sent[-1][0]
    queued = draft_post(publish_at=datetime(2026, 11, 10, 6, tzinfo=UTC))
    repo.dirs["content/queue"] = [f"{queued.id}.md"]
    repo.files[(f"content/queue/{queued.id}.md", None)] = (render_post(queued), "s")
    commands.handle_text("/cola")
    assert "2026-11-10 09:00 (Europe/Moscow)" in chat.sent[-1][0]
    done = Post(id="2026-10-12-x", source="note", source_ref="n", status=PUBLISHED,
                created_at=NOW, body="b", linkedin_urn="urn:li:share:9", published_at=NOW)
    repo.dirs["content/published"] = ["2026-10-12-x.md"]
    repo.files[("content/published/2026-10-12-x.md", None)] = (render_post(done), "s")
    commands.handle_text("/publicados")
    assert "feed/update/urn:li:share:9" in chat.sent[-1][0]
    commands.handle_text("/token")
    assert "quedan <b>31</b> días" in chat.sent[-1][0]


# --- service ---------------------------------------------------------------------------

def test_authorized_only_owner_chat():
    owner = {"message": {"chat": {"id": 42}, "text": "/cola"}}
    stranger = {"message": {"chat": {"id": 7}, "text": "/cola"}}
    button = {"callback_query": {"from": {"id": 42}, "data": "approve:8"}}
    assert authorized(owner, "42") and authorized(button, "42")
    assert not authorized(stranger, "42")


def test_dispatch_routes_and_ignores_strangers():
    calls = []

    class Commands:
        def handle_text(self, text):
            calls.append(("text", text))

        def handle_callback(self, cid, data, mid):
            calls.append(("cb", cid, data, mid))

    dispatch({"update_id": 1, "message": {"chat": {"id": 42}, "text": "/cola"}}, Commands(), "42")
    dispatch({"update_id": 2, "callback_query": {"id": "q", "from": {"id": 42}, "data": "approve:8",
                                                  "message": {"message_id": 5}}}, Commands(), "42")
    dispatch({"update_id": 3, "message": {"chat": {"id": 7}, "text": "/cola"}}, Commands(), "42")
    assert calls == [("text", "/cola"), ("cb", "q", "approve:8", 5)]


def test_run_forever_retries_and_confirms_offsets():
    class Api:
        def __init__(self):
            self.offsets, self.calls = [], 0

        def set_commands(self, commands):
            pass

        def get_updates(self, offset, timeout):
            self.calls += 1
            self.offsets.append(offset)
            if self.calls == 1:
                raise TelegramError("getUpdates: network down")
            if self.calls == 2:
                return [{"update_id": 10, "message": {"chat": {"id": 42}, "text": "/x"}}]
            return []

        def scrub(self, text):
            return text

    class Commands:
        def __init__(self):
            self.texts = []

        def handle_text(self, text):
            self.texts.append(text)
            raise RuntimeError("bug in a handler must not stop the loop")

    api, commands, sleeps = Api(), Commands(), []
    run_forever(api, commands, "42", sleep=sleeps.append, should_stop=lambda: api.calls >= 3)
    assert sleeps == [5]
    assert api.offsets == [None, None, 11]
    assert commands.texts == ["/x"]


# --- API clients -------------------------------------------------------------------------

def test_bot_api_scrubs_token_and_raises_on_not_ok():
    api = BotApi(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": False, "description": "Conflict"}))), TOKEN)
    with pytest.raises(TelegramError, match="getUpdates: Conflict"):
        api.get_updates(None)

    def boom(request):
        raise httpx.ConnectError(f"cannot reach /bot{TOKEN}/getUpdates")

    api = BotApi(httpx.Client(transport=httpx.MockTransport(boom)), TOKEN)
    with pytest.raises(TelegramError) as info:
        api.get_updates(5)
    assert TOKEN not in str(info.value)


def test_bot_api_get_updates_payload():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": []})

    BotApi(httpx.Client(transport=httpx.MockTransport(handler)), TOKEN).get_updates(11, 50)
    assert seen["body"] == {"timeout": 50, "allowed_updates": ["message", "callback_query"],
                            "offset": 11}


def test_inline_keyboard_groups_callback_buttons():
    rows = inline_keyboard([("📝 Revisar PR", "https://x"), ("✅", "cb:approve:8"),
                            ("❌", "cb:reject:8")])
    assert rows == [[{"text": "📝 Revisar PR", "url": "https://x"}],
                    [{"text": "✅", "callback_data": "approve:8"},
                     {"text": "❌", "callback_data": "reject:8"}]]


def github(handler):
    return GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), "o/r", "pat")


def test_github_merge_close_and_files():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, dict(request.url.params),
                     json.loads(request.content) if request.content else None))
        if request.method == "GET" and request.url.path.endswith("/contents/a.md"):
            return httpx.Response(200, json={"type": "file", "sha": "s1",
                                             "content": base64.b64encode("hola ñ".encode()).decode()})
        if request.method == "GET" and request.url.path.endswith("/contents/content/ideas"):
            return httpx.Response(200, json=[{"type": "file", "name": "b.md"},
                                             {"type": "dir", "name": "sub"}])
        if request.method == "PUT" and request.url.path.endswith("/contents/new.md"):
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"merged": True})

    client = github(handler)
    client.merge_pull_request(8)
    client.close_pull_request(9)
    assert client.read_file("a.md", ref="post/x") == ("hola ñ", "s1")
    assert client.list_dir("content/ideas") == ["b.md"]
    client.write_file("new.md", "texto", "msg", sha="s0", branch="post/x")
    assert seen[0][:2] == ("PUT", "/repos/o/r/pulls/8/merge") and seen[0][3] == {"merge_method": "merge"}
    assert seen[1][:2] == ("PATCH", "/repos/o/r/pulls/9") and seen[1][3] == {"state": "closed"}
    assert seen[2][2] == {"ref": "post/x"}
    put = seen[-1][3]
    assert base64.b64decode(put["content"]).decode() == "texto"
    assert put["sha"] == "s0" and put["branch"] == "post/x" and put["message"] == "msg"


def test_github_errors():
    client = github(lambda r: httpx.Response(405, text="not mergeable"))
    with pytest.raises(GitHubError, match="405"):
        client.merge_pull_request(8)
    assert github(lambda r: httpx.Response(404)).read_file("x.md") is None
    assert github(lambda r: httpx.Response(404)).list_dir("x") == []


def test_logging_never_records_request_urls(tmp_path):
    import logging

    from linkedin_bot.telegram_bot.service import setup_logging

    path = tmp_path / "bot.log"
    setup_logging(path)
    try:
        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"ok": True, "result": []})))
        BotApi(client, TOKEN).get_updates(None)
        logging.getLogger("linkedin_bot.telegram").info("hello")
    finally:
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)
    text = path.read_text(encoding="utf-8")
    assert "hello" in text and TOKEN not in text and "api.telegram.org" not in text
