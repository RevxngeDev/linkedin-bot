"""Text of each Telegram notification (Spanish, Telegram HTML). Pure functions.

Each returns (html_text, buttons). User-provided content is always escaped; long bodies
are cut so the whole message stays under Telegram's 4096-character limit.
"""

from __future__ import annotations

from linkedin_bot.notify.telegram import Button, esc

MAX_BODY_CHARS = 2500
MAX_CHECK_CHARS = 900


def _cut(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " […]"


def linkedin_post_url(post_urn: str) -> str:
    # Documented post URL form: https://www.linkedin.com/feed/update/<post urn>/
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


def draft_opened(
    kind: str, source: str, body: str, fact_check: str, pr_url: str, pr_number: int
) -> tuple[str, list[Button]]:
    text = (
        f"📝 <b>Nuevo borrador</b> ({esc(kind)})\n"
        f"Fuente: <code>{esc(source)}</code>\n\n"
        f"<blockquote expandable>{esc(_cut(body, MAX_BODY_CHARS))}</blockquote>\n\n"
        f"🔎 <b>Verificación automática</b>\n{esc(_cut(fact_check, MAX_CHECK_CHARS))}\n\n"
        f"Revisa, edita si hace falta y haz merge del PR #{pr_number} para publicarlo."
    )
    return text, [("📝 Revisar PR", pr_url)]


def published(post_id: str, post_urn: str, body: str) -> tuple[str, list[Button]]:
    text = (
        f"✅ <b>Publicado en LinkedIn</b>\n<code>{esc(post_id)}</code>\n\n"
        f"<blockquote expandable>{esc(_cut(body, 600))}</blockquote>"
    )
    return text, [("🔗 Ver en LinkedIn", linkedin_post_url(post_urn))]


def problem(title: str, detail: str, link: Button | None = None) -> tuple[str, list[Button]]:
    text = f"⚠️ <b>{esc(title)}</b>\n\n{esc(_cut(detail, 1500))}"
    return text, [link] if link else []


def weekly_summary(
    published_posts: list[tuple[str, str]],
    queued_ids: list[str],
    open_pulls: list[tuple[int, str, str]],
    token_days_left: int | None,
    repo_url: str,
) -> tuple[str, list[Button]]:
    """published_posts: (post_id, urn); open_pulls: (number, title, url)."""
    lines = ["📊 <b>Resumen semanal de linkedin-bot</b>", ""]
    lines.append(f"✅ Publicados en los últimos 7 días: <b>{len(published_posts)}</b>")
    lines += [
        f'  • <a href="{esc(linkedin_post_url(urn))}">{esc(post_id)}</a>'
        for post_id, urn in published_posts
    ]
    lines.append(f"🕒 En cola para publicar: <b>{len(queued_ids)}</b>")
    lines += [f"  • {esc(post_id)}" for post_id in queued_ids]
    lines.append(f"📝 Borradores esperando tu revisión: <b>{len(open_pulls)}</b>")
    lines += [
        f'  • <a href="{esc(url)}">#{number} {esc(title)}</a>' for number, title, url in open_pulls
    ]
    if token_days_left is not None:
        icon = "🔑" if token_days_left > 14 else "⚠️"
        lines.append(f"{icon} Token de LinkedIn: caduca en <b>{token_days_left}</b> días")
    return "\n".join(lines), [("📂 Abrir el repositorio", repo_url)]
