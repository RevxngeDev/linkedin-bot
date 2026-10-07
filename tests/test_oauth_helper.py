from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from linkedin_bot.auth import oauth_helper as oh


def test_authorization_url_contains_required_params():
    url = oh.build_authorization_url("cid", "http://localhost:8765/callback", "st4te")
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == oh.AUTHORIZATION_URL
    assert params == {
        "response_type": "code",
        "client_id": "cid",
        "redirect_uri": "http://localhost:8765/callback",
        "state": "st4te",
        "scope": "openid profile w_member_social",
    }


def test_parse_callback_returns_code():
    assert oh.parse_callback("/callback?code=abc&state=s1", "s1") == "abc"


def test_parse_callback_rejects_state_mismatch():
    with pytest.raises(oh.OAuthError, match="State mismatch"):
        oh.parse_callback("/callback?code=abc&state=evil", "s1")


def test_parse_callback_reports_denial():
    with pytest.raises(oh.OAuthError, match="user_cancelled_authorize"):
        oh.parse_callback("/callback?error=user_cancelled_authorize&state=s1", "s1")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exchange_code_posts_form_and_returns_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = parse_qs(request.content.decode())
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 5184000})

    payload = oh.exchange_code(_client(handler), "code1", "cid", "secret", "http://x/cb")
    assert payload["access_token"] == "tok"
    assert seen["url"] == oh.TOKEN_URL
    assert seen["body"]["grant_type"] == ["authorization_code"]
    assert seen["body"]["code"] == ["code1"]


def test_exchange_code_raises_on_error_status():
    client = _client(lambda r: httpx.Response(401, text="bad code"))
    with pytest.raises(oh.OAuthError, match="401"):
        oh.exchange_code(client, "c", "cid", "s", "http://x/cb")


def test_fetch_member_urn_uses_sub_claim():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"sub": "782bbtaQ", "name": "X"})

    assert oh.fetch_member_urn(_client(handler), "tok") == "urn:li:person:782bbtaQ"


def test_build_token_result_computes_expiry():
    now = datetime(2026, 10, 6, tzinfo=UTC)
    result = oh.build_token_result(
        {"access_token": "tok", "expires_in": 5184000, "scope": "openid"}, "urn:li:person:1", now
    )
    assert result.expires_at == datetime(2026, 12, 5, tzinfo=UTC)


def test_http_client_ignores_system_proxy_env(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks4://127.0.0.1:10808")
    monkeypatch.setenv("HTTPS_PROXY", "socks4://127.0.0.1:10808")
    with oh.build_http_client(None) as client:
        assert client._trust_env is False


def test_http_client_accepts_explicit_http_proxy():
    with oh.build_http_client("http://127.0.0.1:12334") as client:
        assert client is not None
