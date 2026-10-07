import httpx
import pytest

from linkedin_bot.publisher.approval import (
    GITHUB_API_VERSION,
    ApprovalError,
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
    with pytest.raises(ApprovalError, match="422"):
        _client(lambda r: httpx.Response(422, text="bad sha")).merged_pull_request("a", "main")
