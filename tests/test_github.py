import json

import httpx
import pytest

from linkedin_bot.repo.github import (
    GITHUB_API_VERSION,
    GitHubError,
    GitHubClient,
)


def _client(handler, token="tkn"):
    return GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), "o/r", token)


def test_returns_merged_pr_into_base_branch():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(
            200,
            json=[
                {"number": 1, "merged_at": None, "base": {"ref": "main"}},
                {"number": 2, "merged_at": "2026-10-08T10:00:00Z", "base": {"ref": "dev"}},
                {"number": 3, "merged_at": "2026-10-08T11:00:00Z", "base": {"ref": "main"}},
            ],
        )

    pull = _client(handler).merged_pull_request("abc123", "main")
    request = seen["request"]
    assert pull["number"] == 3
    assert str(request.url) == "https://api.github.com/repos/o/r/commits/abc123/pulls"
    assert request.headers["Authorization"] == "Bearer tkn"
    assert request.headers["X-GitHub-Api-Version"] == GITHUB_API_VERSION


def test_direct_push_has_no_merged_pr():
    assert _client(lambda r: httpx.Response(200, json=[])).merged_pull_request("a", "main") is None


def test_no_auth_header_without_token():
    def handler(request):
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=[])

    _client(handler, token=None).merged_pull_request("a", "main")


def test_api_error_raises():
    with pytest.raises(GitHubError, match="422"):
        _client(lambda r: httpx.Response(422, text="bad sha")).merged_pull_request("a", "main")


def test_pull_requests_for_branch_queries_all_states():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json=[{"number": 4, "state": "closed"}])

    pulls = _client(handler).pull_requests_for_branch("post/idea-x")
    params = dict(seen["request"].url.params)
    assert pulls == [{"number": 4, "state": "closed"}]
    assert seen["request"].url.path == "/repos/o/r/pulls"
    assert params == {"head": "o:post/idea-x", "state": "all"}


def test_create_pull_request_posts_payload():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(201, json={"number": 9, "html_url": "https://x/9"})

    pull = _client(handler).create_pull_request("post/idea-x", "main", "T", "B")
    body = json.loads(seen["request"].content)
    assert pull["number"] == 9
    assert seen["request"].method == "POST"
    assert str(seen["request"].url) == "https://api.github.com/repos/o/r/pulls"
    assert body == {"head": "post/idea-x", "base": "main", "title": "T", "body": "B"}


def test_create_pull_request_error_raises():
    client = _client(lambda r: httpx.Response(403, text="Actions may not create PRs"))
    with pytest.raises(GitHubError, match="403"):
        client.create_pull_request("h", "main", "T", "B")
