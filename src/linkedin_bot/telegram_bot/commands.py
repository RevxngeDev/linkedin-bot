"""Commands and buttons of the listening Telegram bot (Telegram T3, D-033).

The bot is a remote control for the repository: approving merges the draft PR (so the
APPROVAL rule and the publisher are unchanged), rejecting closes it, scheduling edits the
draft's `publish_at`, notes and watched repos are commits to `main`. Every write needs an
explicit confirmation button or an explicit command; only `post/...` draft PRs can be
merged or closed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import yaml

from linkedin_bot.notify.messages import draft_buttons, linkedin_post_url
from linkedin_bot.notify.telegram import Button, esc
from linkedin_bot.ops.token_reminder import TokenConfigError, load_token_config_text
from linkedin_bot.repo.github import GitHubError
from linkedin_bot.sources.projects import REPO_PATTERN
from linkedin_bot.store.posts import StoreError, parse_post, render_post

DRAFT_BRANCH_PREFIX = "post/"
POST_FILE = re.compile(r"Post file: `(content/queue/[^`]+\.md)`")
WATCHED_REPOS_PATH = "config/watched_repos.yml"
WATCHED_REPOS_HEADER = """\
# Public repos the generator watches for project posts (D-018, D-029).
# First run per repo: an introduction draft. Afterwards: at most one update draft per
# repo every `update_interval_days`, only if it has new commits. Every draft is a PR.
# Also editable from Telegram: /repo_add, /repo_remove (D-033).
"""
MAX_NOTE_SLUG_WORDS = 6

COMMANDS: list[tuple[str, str]] = [
    ("pendientes", "Borradores esperando tu aprobación"),
    ("cola", "Posts aprobados que esperan publicarse"),
    ("publicados", "Últimos posts publicados"),
    ("nota", "Crear una nota: /nota <texto>"),
    ("programar", "Programar un borrador: /programar <PR> <AAAA-MM-DD> <HH:MM>"),
    ("repos", "Repos vigilados"),
    ("repo_add", "Vigilar un repo: /repo_add usuario/repo"),
    ("repo_remove", "Dejar de vigilar: /repo_remove usuario/repo"),
    ("token", "Caducidad del token de LinkedIn"),
    ("ayuda", "Qué puedo hacer"),
]

HELP = """🤖 <b>linkedin-bot</b> — mando a distancia

<b>Borradores</b>
/pendientes — borradores esperando tu aprobación (con botones ✅ ❌)
/programar &lt;PR&gt; &lt;AAAA-MM-DD&gt; &lt;HH:MM&gt; — fija cuándo se publica (hora {tz})
/programar &lt;PR&gt; quitar — vuelve a "lo antes posible"

<b>Contenido</b>
/nota &lt;texto&gt; — crea una nota; el bot redactará un borrador
/cola — aprobados que esperan publicarse
/publicados — últimos posts publicados

<b>Repos vigilados</b>
/repos · /repo_add usuario/repo · /repo_remove usuario/repo

<b>Otros</b>
/token — caducidad del token de LinkedIn"""


class RepoPort(Protocol):
    def get_pull_request(self, number: int) -> dict: ...
    def merge_pull_request(self, number: int) -> dict: ...
    def close_pull_request(self, number: int) -> dict: ...
    def list_pull_requests(self) -> list[dict]: ...
    def read_file(self, path: str, ref: str | None = None) -> tuple[str, str] | None: ...
    def list_dir(self, path: str, ref: str | None = None) -> list[str]: ...
    def write_file(
        self, path: str, text: str, message: str, sha: str | None = None, branch: str | None = None
    ) -> None: ...
    def get_repository(self, repo: str) -> dict: ...


class ChatPort(Protocol):
    def send(self, text: str, buttons: list[Button] | tuple = ()) -> None: ...
    def answer(self, callback_id: str, text: str = "") -> None: ...
    def set_buttons(self, message_id: int, buttons: list[Button]) -> None: ...


def slugify(text: str, max_words: int = MAX_NOTE_SLUG_WORDS) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_text.lower())[:max_words]
    return "-".join(words) or "nota"


class BotCommands:
    def __init__(
        self,
        repo: RepoPort,
        chat: ChatPort,
        timezone: ZoneInfo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        log: Callable[[str], None] = print,
    ) -> None:
        self._repo = repo
        self._chat = chat
        self._tz = timezone
        self._clock = clock
        self._log = log

    # --- entry points -------------------------------------------------------------------

    def handle_text(self, text: str) -> None:
        text = text.strip()
        if not text.startswith("/"):
            self._chat.send("Usa /ayuda para ver los comandos. Para guardar una idea: /nota …")
            return
        command, _, args = text.partition(" ")
        command = command[1:].split("@", 1)[0].lower()
        handlers = {
            "start": self._help, "ayuda": self._help, "help": self._help,
            "pendientes": self._pending, "cola": self._queue, "publicados": self._published,
            "nota": self._note, "programar": self._schedule, "repos": self._repos,
            "repo_add": self._repo_add, "repo_remove": self._repo_remove, "token": self._token,
        }
        handler = handlers.get(command)
        if handler is None:
            self._chat.send(f"No conozco /{esc(command)}. Usa /ayuda.")
            return
        try:
            handler(args.strip())
        except (GitHubError, StoreError, TokenConfigError) as exc:
            self._log(f"/{command} failed: {exc}")
            self._chat.send(f"⚠️ No pude completar /{esc(command)}: {esc(exc)}")

    def handle_callback(self, callback_id: str, data: str, message_id: int) -> None:
        action, _, raw_number = data.partition(":")
        if not raw_number.isdigit():
            self._chat.answer(callback_id, "Botón no reconocido")
            return
        number = int(raw_number)
        try:
            pull = self._repo.get_pull_request(number)
            if not pull.get("head", {}).get("ref", "").startswith(DRAFT_BRANCH_PREFIX):
                self._chat.answer(callback_id, "Ese PR no es un borrador del bot")
                return
            if pull.get("state") != "open":
                verb = "fusionado" if pull.get("merged_at") else "cerrado"
                self._chat.answer(callback_id, f"El PR #{number} ya estaba {verb}")
                self._chat.set_buttons(message_id, [("📝 Ver PR", pull["html_url"])])
                return
            self._dispatch_callback(action, number, pull, callback_id, message_id)
        except GitHubError as exc:
            self._log(f"callback {data} failed: {exc}")
            self._chat.answer(callback_id, "No se pudo completar")
            self._chat.send(f"⚠️ No pude completar la acción sobre el PR #{number}: {esc(exc)}")

    # --- callbacks --------------------------------------------------------------------------

    def _dispatch_callback(
        self, action: str, number: int, pull: dict, callback_id: str, message_id: int
    ) -> None:
        url = pull["html_url"]
        if action == "approve":
            self._chat.answer(callback_id, "¿Seguro? Confirma para publicar")
            self._chat.set_buttons(message_id, [
                ("✅ Sí, aprobar y publicar", f"cb:approve!:{number}"),
                ("↩️ Cancelar", f"cb:cancel:{number}"),
            ])
        elif action == "reject":
            self._chat.answer(callback_id, "¿Seguro? Confirma para rechazar")
            self._chat.set_buttons(message_id, [
                ("❌ Sí, rechazar", f"cb:reject!:{number}"),
                ("↩️ Cancelar", f"cb:cancel:{number}"),
            ])
        elif action == "cancel":
            self._chat.answer(callback_id, "Cancelado")
            self._chat.set_buttons(message_id, draft_buttons(url, number))
        elif action == "approve!":
            self._repo.merge_pull_request(number)
            self._chat.answer(callback_id, "Aprobado")
            self._chat.set_buttons(message_id, [("📝 Ver PR", url)])
            self._chat.send(
                f"✅ PR #{number} aprobado (merge hecho). Se publicará en la próxima ejecución "
                "del publicador (máximo un post por día) y te avisaré aquí."
            )
        elif action == "reject!":
            self._repo.close_pull_request(number)
            self._chat.answer(callback_id, "Rechazado")
            self._chat.set_buttons(message_id, [("📝 Ver PR", url)])
            self._chat.send(
                f"❌ PR #{number} cerrado. Ese borrador no se publicará ni se volverá a redactar."
            )
        else:
            self._chat.answer(callback_id, "Botón no reconocido")

    # --- commands ----------------------------------------------------------------------------

    def _help(self, _: str) -> None:
        self._chat.send(HELP.format(tz=esc(self._tz.key)))

    def _open_drafts(self) -> list[dict]:
        return [
            p for p in self._repo.list_pull_requests()
            if p.get("state") == "open"
            and p.get("head", {}).get("ref", "").startswith(DRAFT_BRANCH_PREFIX)
        ]

    def _pending(self, _: str) -> None:
        drafts = self._open_drafts()
        if not drafts:
            self._chat.send("No hay borradores esperando tu aprobación. 🎉")
            return
        self._chat.send(f"📝 <b>{len(drafts)} borrador(es) esperando tu aprobación</b>")
        for pull in sorted(drafts, key=lambda p: p["number"]):
            self._chat.send(
                f"<b>#{pull['number']}</b> {esc(pull.get('title', ''))}\n"
                f"Abierto: {esc(pull.get('created_at', '')[:10])}",
                draft_buttons(pull["html_url"], pull["number"]),
            )

    def _read_posts(self, directory: str) -> list:
        posts = []
        for name in self._repo.list_dir(directory):
            if not name.endswith(".md"):
                continue
            found = self._repo.read_file(f"{directory}/{name}")
            if found:
                posts.append(parse_post(found[0]))
        return posts

    def _local(self, moment: datetime) -> str:
        return f"{moment.astimezone(self._tz):%Y-%m-%d %H:%M} ({self._tz.key})"

    def _queue(self, _: str) -> None:
        posts = sorted(self._read_posts("content/queue"),
                       key=lambda p: (p.publish_at or p.created_at, p.id))
        if not posts:
            self._chat.send("La cola está vacía: no hay posts aprobados esperando.")
            return
        lines = [f"🕒 <b>{len(posts)} post(s) en cola</b>"]
        for post in posts:
            when = self._local(post.publish_at) if post.publish_at else "lo antes posible"
            lines.append(f"• <code>{esc(post.id)}</code> — {esc(when)} [{esc(post.status)}]")
        self._chat.send("\n".join(lines))

    def _published(self, _: str) -> None:
        names = [n for n in self._repo.list_dir("content/published") if n.endswith(".md")]
        if not names:
            self._chat.send("Todavía no hay posts publicados.")
            return
        lines = ["✅ <b>Últimos publicados</b>"]
        for name in sorted(names)[-5:][::-1]:
            found = self._repo.read_file(f"content/published/{name}")
            if not found:
                continue
            post = parse_post(found[0])
            when = self._local(post.published_at) if post.published_at else "?"
            link = linkedin_post_url(post.linkedin_urn) if post.linkedin_urn else ""
            lines.append(f'• <a href="{esc(link)}">{esc(post.id)}</a> — {esc(when)}')
        self._chat.send("\n".join(lines))

    def _note(self, text: str) -> None:
        if not text:
            self._chat.send("Escribe la nota después del comando: /nota Terminé el panel de …")
            return
        existing = set(self._repo.list_dir("content/ideas"))
        base = slugify(text)
        slug, counter = base, 2
        while f"{slug}.md" in existing:
            slug, counter = f"{base}-{counter}", counter + 1
        path = f"content/ideas/{slug}.md"
        self._repo.write_file(path, text.strip() + "\n", f"Add note {slug} from Telegram")
        self._chat.send(
            f"📝 Nota guardada como <code>{esc(path)}</code>. En unos minutos te llegará el "
            "borrador para aprobar."
        )

    def _schedule(self, args: str) -> None:
        parts = args.split()
        if len(parts) not in (2, 3) or not parts[0].lstrip("#").isdigit():
            self._chat.send(
                "Uso: /programar &lt;PR&gt; &lt;AAAA-MM-DD&gt; &lt;HH:MM&gt; "
                f"(hora {esc(self._tz.key)}) · o /programar &lt;PR&gt; quitar"
            )
            return
        number = int(parts[0].lstrip("#"))
        clear = len(parts) == 2 and parts[1].lower() == "quitar"
        when: datetime | None = None
        if not clear:
            try:
                local = datetime.strptime(" ".join(parts[1:3]), "%Y-%m-%d %H:%M")
            except ValueError:
                self._chat.send("Fecha u hora no válidas. Ejemplo: /programar 7 2026-11-10 09:00")
                return
            when = local.replace(tzinfo=self._tz).astimezone(UTC)
            if when <= self._clock():
                self._chat.send("Esa fecha ya pasó. Elige una fecha futura.")
                return
        pull = self._repo.get_pull_request(number)
        branch = pull.get("head", {}).get("ref", "")
        if pull.get("state") != "open" or not branch.startswith(DRAFT_BRANCH_PREFIX):
            self._chat.send(f"El PR #{number} no es un borrador abierto del bot.")
            return
        match = POST_FILE.search(pull.get("body") or "")
        if not match:
            self._chat.send(f"No encuentro el archivo del post en el PR #{number}.")
            return
        path = match.group(1)
        found = self._repo.read_file(path, ref=branch)
        if not found:
            self._chat.send(f"No encuentro {esc(path)} en la rama del PR #{number}.")
            return
        text, sha = found
        post = replace(parse_post(text), publish_at=when)
        message = (f"Schedule {post.id} for {when.isoformat()}" if when
                   else f"Unschedule {post.id}")
        self._repo.write_file(path, render_post(post), message, sha=sha, branch=branch)
        if when:
            self._chat.send(
                f"🗓 PR #{number} programado para el {esc(self._local(when))}. "
                "Cuando lo apruebes, no se publicará antes de esa hora."
            )
        else:
            self._chat.send(f"🗓 PR #{number} sin fecha: se publicará lo antes posible al aprobarlo.")

    def _read_watch(self) -> tuple[dict, str | None]:
        found = self._repo.read_file(WATCHED_REPOS_PATH)
        if not found:
            return {"update_interval_days": 7, "repos": []}, None
        data = yaml.safe_load(found[0]) or {}
        data.setdefault("repos", [])
        return data, found[1]

    def _write_watch(self, data: dict, sha: str | None, message: str) -> None:
        body = yaml.safe_dump(
            {"update_interval_days": data.get("update_interval_days", 7), "repos": data["repos"]},
            sort_keys=False,
        )
        self._repo.write_file(WATCHED_REPOS_PATH, WATCHED_REPOS_HEADER + body, message, sha=sha)

    def _repos(self, _: str) -> None:
        data, _sha = self._read_watch()
        repos = data["repos"]
        if not repos:
            self._chat.send("No vigilo ningún repo. Añade uno con /repo_add usuario/repo")
            return
        lines = [f"👀 <b>Repos vigilados</b> (actualización cada {data.get('update_interval_days', 7)} días)"]
        lines += [f'• <a href="https://github.com/{esc(r)}">{esc(r)}</a>' for r in repos]
        self._chat.send("\n".join(lines))

    def _repo_add(self, repo: str) -> None:
        if not REPO_PATTERN.match(repo):
            self._chat.send("Uso: /repo_add usuario/repo (por ejemplo RevxngeDev/Gepeto)")
            return
        data, sha = self._read_watch()
        if repo in data["repos"]:
            self._chat.send(f"Ya vigilo {esc(repo)}.")
            return
        info = self._repo.get_repository(repo)
        if info.get("private"):
            self._chat.send(f"{esc(repo)} es privado: solo vigilo repos públicos.")
            return
        data["repos"].append(info.get("full_name", repo))
        self._write_watch(data, sha, f"Watch {repo} (from Telegram)")
        self._chat.send(
            f"👀 Ahora vigilo {esc(repo)}. En unos minutos te llegará su borrador de presentación."
        )

    def _repo_remove(self, repo: str) -> None:
        data, sha = self._read_watch()
        match = next((r for r in data["repos"] if r.lower() == repo.lower()), None)
        if not repo or match is None:
            self._chat.send(f"No vigilo {esc(repo) or 'ese repo'}. Usa /repos para ver la lista.")
            return
        if len(data["repos"]) == 1:
            self._chat.send("Es el único repo vigilado; la lista no puede quedar vacía.")
            return
        data["repos"].remove(match)
        self._write_watch(data, sha, f"Stop watching {match} (from Telegram)")
        self._chat.send(f"🛑 Dejé de vigilar {esc(match)}.")

    def _token(self, _: str) -> None:
        found = self._repo.read_file("config/linkedin_token.yml")
        if not found:
            self._chat.send("No encuentro config/linkedin_token.yml.")
            return
        config = load_token_config_text(found[0])
        days = (config.expires_at - self._clock()).days
        icon = "🔑" if days > config.remind_days_before else "⚠️"
        self._chat.send(
            f"{icon} El token de LinkedIn caduca el {esc(self._local(config.expires_at))}: "
            f"quedan <b>{days}</b> días."
        )
