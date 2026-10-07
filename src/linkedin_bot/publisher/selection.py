"""Decide which queued post (if any) may be published now.

Rules (PROJECT_CONTEXT invariants):
- IDEMPOTENCY: a post whose id is already in published/ is never selected again.
- A post left in "publishing" state means an earlier run may have published it without
  recording the result; everything stops until the owner resolves it (D-019).
- RATE: at most one post per UTC calendar day (D-013).
- A post with `publish_at` in the future waits; the oldest due post goes first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from linkedin_bot.store.posts import PUBLISHING, QUEUED, Post


@dataclass(frozen=True)
class Selection:
    post: Post | None
    reason: str
    blocked: bool = False


def select_next(queue: list[Post], published: list[Post], now: datetime) -> Selection:
    stuck = [p for p in queue if p.status == PUBLISHING]
    if stuck:
        ids = ", ".join(p.id for p in stuck)
        return Selection(
            None,
            f"Post(s) stuck in 'publishing': {ids}. Check LinkedIn manually before "
            "continuing (see COMMANDS.md).",
            blocked=True,
        )

    today = now.date()
    if any(p.published_at and p.published_at.date() == today for p in published):
        return Selection(None, f"A post was already published today ({today} UTC).")

    published_ids = {p.id for p in published}
    due = [
        p
        for p in queue
        if p.status == QUEUED
        and p.id not in published_ids
        and (p.publish_at is None or p.publish_at <= now)
    ]
    if not due:
        return Selection(None, "No queued post is due.")

    due.sort(key=lambda p: (p.publish_at or p.created_at, p.id))
    return Selection(due[0], f"Selected {due[0].id}.")
