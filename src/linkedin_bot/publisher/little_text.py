"""Convert plain post text to LinkedIn's "little" text format.

The Posts API `commentary` field treats these characters as syntax, so every one must be
escaped with a backslash to appear literally: | { } @ [ ] ( ) < > # \\ * _ ~
Hashtags (#word) are turned into the HashtagTemplate so they stay clickable.
Source: https://learn.microsoft.com/linkedin/marketing/community-management/shares/little-text-format
(view li-lms-2026-09, read 2026-10-08).
"""

from __future__ import annotations

import re

RESERVED = frozenset("|{}@[]()<>#\\*_~")
# '#' followed by letters/digits, not preceded by a word character (so "C#" stays text).
HASHTAG = re.compile(r"(?<![\w\\])#([^\W_]+)")


def escape(text: str) -> str:
    return "".join(f"\\{char}" if char in RESERVED else char for char in text)


def to_little_text(text: str) -> str:
    parts: list[str] = []
    position = 0
    for match in HASHTAG.finditer(text):
        parts.append(escape(text[position : match.start()]))
        parts.append(f"{{hashtag|\\#|{match.group(1)}}}")
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)
