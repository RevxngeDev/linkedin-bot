from datetime import UTC, datetime, timedelta

from linkedin_bot.publisher.selection import select_next
from linkedin_bot.store.posts import PUBLISHED, PUBLISHING, QUEUED, Post

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def make(post_id, status=QUEUED, created=NOW - timedelta(days=1), **kwargs):
    return Post(
        id=post_id,
        source="note",
        source_ref="x",
        status=status,
        created_at=created,
        body="b",
        **kwargs,
    )


def published(post_id, at):
    return make(post_id, status=PUBLISHED, linkedin_urn="urn:li:share:1", published_at=at)


def test_selects_oldest_due_post():
    old = make("b-old", created=NOW - timedelta(days=3))
    new = make("a-new", created=NOW - timedelta(days=1))
    assert select_next([new, old], [], NOW).post == old


def test_nothing_due_when_queue_empty():
    selection = select_next([], [], NOW)
    assert selection.post is None and not selection.blocked


def test_rate_limit_one_per_utc_day():
    already = published("earlier", NOW.replace(hour=0, minute=5))
    selection = select_next([make("next")], [already], NOW)
    assert selection.post is None
    assert "already published today" in selection.reason


def test_post_published_yesterday_does_not_block_today():
    yesterday = published("earlier", NOW - timedelta(days=1))
    assert select_next([make("next")], [yesterday], NOW).post.id == "next"


def test_never_selects_an_id_already_published():
    old = published("same-id", NOW - timedelta(days=5))
    assert select_next([make("same-id")], [old], NOW).post is None


def test_future_publish_at_waits_and_past_one_is_due():
    future = make("future", publish_at=NOW + timedelta(hours=1))
    assert select_next([future], [], NOW).post is None
    past = make("past", publish_at=NOW - timedelta(minutes=1))
    assert select_next([future, past], [], NOW).post == past


def test_publish_at_orders_before_created_at():
    scheduled = make("scheduled", created=NOW, publish_at=NOW - timedelta(days=10))
    plain = make("plain", created=NOW - timedelta(days=2))
    assert select_next([plain, scheduled], [], NOW).post == scheduled


def test_stuck_publishing_post_blocks_everything():
    stuck = make("stuck", status=PUBLISHING, claimed_at=NOW - timedelta(hours=2))
    selection = select_next([stuck, make("other")], [], NOW)
    assert selection.post is None
    assert selection.blocked
    assert "stuck" in selection.reason
