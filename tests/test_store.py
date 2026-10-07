from dataclasses import replace
from datetime import UTC, datetime

import pytest

from linkedin_bot.store.posts import (
    PUBLISHED,
    PostStore,
    StoreError,
    parse_post,
    render_post,
)

SAMPLE = """---
id: 2026-10-08-hello
source: note
source_ref: content/ideas/hello.md
status: queued
created_at: '2026-10-08T09:00:00+00:00'
---

Hola, este es el cuerpo.

Segundo párrafo.
"""


def _published(post):
    return replace(
        post,
        status=PUBLISHED,
        linkedin_urn="urn:li:share:1",
        published_at=datetime(2026, 10, 8, 10, tzinfo=UTC),
    )


def test_parse_sample():
    post = parse_post(SAMPLE)
    assert post.id == "2026-10-08-hello"
    assert post.status == "queued"
    assert post.created_at == datetime(2026, 10, 8, 9, tzinfo=UTC)
    assert post.publish_at is None
    assert post.body == "Hola, este es el cuerpo.\n\nSegundo párrafo."


def test_render_then_parse_roundtrip():
    published = _published(parse_post(SAMPLE))
    assert parse_post(render_post(published)) == published


def test_unquoted_yaml_timestamp_and_naive_value_become_utc():
    text = SAMPLE.replace("'2026-10-08T09:00:00+00:00'", "2026-10-08 09:00:00")
    assert parse_post(text).created_at == datetime(2026, 10, 8, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda t: t.replace("---\n", "", 1), "frontmatter"),
        (lambda t: t.replace("status: queued", "status: draft"), "status"),
        (lambda t: t.replace("id: 2026-10-08-hello", "id: Hello World"), "id"),
        (lambda t: t.replace("source: note\n", ""), "source"),
        (lambda t: t.replace("source: note", "source: note\nfoo: 1"), "unknown"),
        (lambda t: t.split("---\n\n")[0] + "---\n\n", "empty"),
        (lambda t: t.replace("'2026-10-08T09:00:00+00:00'", "'yesterday'"), "created_at"),
    ],
)
def test_parse_rejects_invalid_files(mutation, message):
    with pytest.raises(StoreError, match=message):
        parse_post(mutation(SAMPLE))


def test_store_lists_saves_and_moves(tmp_path):
    store = PostStore(tmp_path)
    post = parse_post(SAMPLE)
    store.save_to_queue(post)
    assert store.list_queue() == [post]
    assert store.list_published() == []

    done = _published(post)
    store.move_to_published(done)
    assert store.list_queue() == []
    assert store.list_published() == [done]


def test_move_requires_published_fields(tmp_path):
    with pytest.raises(StoreError, match="only a published post"):
        PostStore(tmp_path).move_to_published(parse_post(SAMPLE))


def test_file_name_must_match_id(tmp_path):
    (tmp_path / "queue").mkdir()
    (tmp_path / "queue" / "other-name.md").write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(StoreError, match="does not match the file name"):
        PostStore(tmp_path).list_queue()
