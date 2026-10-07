import json

import httpx
import pytest

from linkedin_bot.publisher.linkedin_client import POSTS_URL, LinkedInClient, PublishError


def _client(handler) -> LinkedInClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LinkedInClient(http, "tok", "202609")


def test_create_text_post_sends_expected_request_and_returns_urn():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})

    urn = _client(handler).create_text_post("urn:li:person:abc", "Hola")
    request = seen["request"]
    body = json.loads(request.content)
    assert urn == "urn:li:share:123"
    assert request.method == "POST" and str(request.url) == POSTS_URL
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["Linkedin-Version"] == "202609"
    assert request.headers["X-Restli-Protocol-Version"] == "2.0.0"
    assert body["author"] == "urn:li:person:abc"
    assert body["commentary"] == "Hola"
    assert body["visibility"] == "PUBLIC"
    assert body["lifecycleState"] == "PUBLISHED"


def test_create_text_post_raises_on_non_201():
    client = _client(lambda r: httpx.Response(403, text="ACCESS_DENIED"))
    with pytest.raises(PublishError, match="403"):
        client.create_text_post("urn:li:person:abc", "Hola")


def test_create_text_post_raises_without_urn_header():
    client = _client(lambda r: httpx.Response(201))
    with pytest.raises(PublishError, match="x-restli-id"):
        client.create_text_post("urn:li:person:abc", "Hola")
