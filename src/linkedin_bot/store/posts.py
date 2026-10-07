"""Post files: Markdown body + YAML frontmatter, stored under content/ (D-007).

This module only reads and writes files. It makes no network calls (see ARCHITECTURE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

import yaml

QUEUED = "queued"
PUBLISHING = "publishing"
PUBLISHED = "published"
STATUSES = (QUEUED, PUBLISHING, PUBLISHED)

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)
DATETIME_FIELDS = ("created_at", "publish_at", "claimed_at", "published_at")


class StoreError(ValueError):
    """Raised when a post file is malformed or inconsistent."""


@dataclass(frozen=True)
class Post:
    id: str
    source: str
    source_ref: str
    status: str
    created_at: datetime
    body: str
    publish_at: datetime | None = None
    claimed_at: datetime | None = None
    linkedin_urn: str | None = None
    published_at: datetime | None = None


def _to_datetime(value: object, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise StoreError(f"{field_name}: invalid ISO datetime {value!r}") from exc
    else:
        raise StoreError(f"{field_name}: expected an ISO datetime, got {value!r}")
    # Naive datetimes are interpreted as UTC (D-013).
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_post(text: str) -> Post:
    match = FRONTMATTER.match(text)
    if not match:
        raise StoreError("missing YAML frontmatter delimited by '---' lines")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise StoreError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise StoreError("frontmatter must be a mapping")

    known = {f.name for f in fields(Post)} - {"body"}
    unknown = set(meta) - known
    if unknown:
        raise StoreError(f"unknown frontmatter field(s): {', '.join(sorted(unknown))}")
    for required in ("id", "source", "source_ref", "status", "created_at"):
        if not meta.get(required):
            raise StoreError(f"missing required field '{required}'")

    values = {name: meta.get(name) for name in known}
    for name in DATETIME_FIELDS:
        values[name] = _to_datetime(values[name], name)
    for name in ("id", "source", "source_ref", "status", "linkedin_urn"):
        if values[name] is not None:
            values[name] = str(values[name])

    if not ID_PATTERN.match(values["id"]):
        raise StoreError(f"id {values['id']!r} must be lowercase letters, digits and '-'")
    if values["status"] not in STATUSES:
        raise StoreError(f"status {values['status']!r} must be one of {', '.join(STATUSES)}")
    body = match.group(2).strip()
    if not body:
        raise StoreError("post body is empty")
    return Post(body=body, **values)


def render_post(post: Post) -> str:
    meta: dict[str, object] = {}
    for f in fields(Post):
        if f.name == "body":
            continue
        value = getattr(post, f.name)
        if value is None:
            continue
        # Datetimes are written as quoted ISO strings so YAML never reinterprets them.
        meta[f.name] = value.isoformat() if isinstance(value, datetime) else value
    frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{frontmatter}---\n\n{post.body.strip()}\n"


class PostStore:
    """Reads and writes post files under `<root>/queue` and `<root>/published`."""

    def __init__(self, root: Path) -> None:
        self.queue_dir = root / "queue"
        self.published_dir = root / "published"

    def queue_path(self, post_id: str) -> Path:
        return self.queue_dir / f"{post_id}.md"

    def published_path(self, post_id: str) -> Path:
        return self.published_dir / f"{post_id}.md"

    def list_queue(self) -> list[Post]:
        return self._load_dir(self.queue_dir)

    def list_published(self) -> list[Post]:
        return self._load_dir(self.published_dir)

    def save_to_queue(self, post: Post) -> Path:
        return self._write(self.queue_path(post.id), post)

    def move_to_published(self, post: Post) -> Path:
        """Write `post` to published/ and remove it from queue/."""
        if post.status != PUBLISHED or not post.linkedin_urn or not post.published_at:
            raise StoreError(f"{post.id}: only a published post with URN and date can move")
        target = self._write(self.published_path(post.id), post)
        self.queue_path(post.id).unlink(missing_ok=True)
        return target

    def _load_dir(self, directory: Path) -> list[Post]:
        if not directory.is_dir():
            return []
        posts = []
        for path in sorted(directory.glob("*.md")):
            try:
                post = parse_post(path.read_text(encoding="utf-8"))
            except StoreError as exc:
                raise StoreError(f"{path}: {exc}") from exc
            if post.id != path.stem:
                raise StoreError(f"{path}: id {post.id!r} does not match the file name")
            posts.append(post)
        return posts

    @staticmethod
    def _write(path: Path, post: Post) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_post(post), encoding="utf-8", newline="\n")
        return path
