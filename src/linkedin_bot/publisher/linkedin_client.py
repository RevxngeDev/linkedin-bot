"""Minimal LinkedIn client. Its only write call is "create post" (see PROJECT_CONTEXT).

Endpoint and headers follow LinkedIn's Posts API docs (view li-lms-2026-09), checked on
2026-10-07: https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api
"""

from __future__ import annotations

import httpx

POSTS_URL = "https://api.linkedin.com/rest/posts"
# Monthly version (YYYYMM). LinkedIn sunsets old versions; override via LINKEDIN_API_VERSION.
DEFAULT_API_VERSION = "202609"


class PublishError(RuntimeError):
    """Raised when LinkedIn does not confirm the post was created."""


class LinkedInClient:
    def __init__(self, http: httpx.Client, access_token: str, api_version: str) -> None:
        self._http = http
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Linkedin-Version": api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def create_text_post(self, author_urn: str, text: str) -> str:
        """Publish a public text post and return its URN (from the x-restli-id header)."""
        body = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        response = self._http.post(POSTS_URL, json=body, headers=self._headers)
        if response.status_code != 201:
            raise PublishError(f"Create post failed ({response.status_code}): {response.text}")
        post_urn = response.headers.get("x-restli-id")
        if not post_urn:
            raise PublishError("LinkedIn returned 201 without an x-restli-id header.")
        return post_urn
