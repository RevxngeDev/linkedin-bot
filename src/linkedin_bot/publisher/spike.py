"""Phase 0 spike: publish one hard-coded text post from GitHub Actions."""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.publisher.linkedin_client import (
    DEFAULT_API_VERSION,
    LinkedInClient,
    PublishError,
)

SPIKE_POST_TEXT = """\
Estoy construyendo linkedin-bot, un pipeline en Python que convierte mis notas y las \
releases de mis proyectos en borradores de posts.

Cada borrador pasa por mi revisión en un Pull Request y solo se publica lo que apruebo, \
usando la API oficial de LinkedIn desde GitHub Actions.

Este es el primer post publicado por el pipeline. Pronto compartiré el repositorio."""


def main() -> None:
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    author_urn = os.environ.get("LINKEDIN_MEMBER_URN", "").strip()
    api_version = os.environ.get("LINKEDIN_API_VERSION", "").strip() or DEFAULT_API_VERSION
    missing = [
        name
        for name, value in (
            ("LINKEDIN_ACCESS_TOKEN", access_token),
            ("LINKEDIN_MEMBER_URN", author_urn),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

    with httpx.Client(timeout=30) as http:
        client = LinkedInClient(http, access_token, api_version)
        try:
            post_urn = client.create_text_post(author_urn, SPIKE_POST_TEXT)
        except PublishError as exc:
            sys.exit(str(exc))
    print(f"Published post URN: {post_urn}")


if __name__ == "__main__":
    main()
