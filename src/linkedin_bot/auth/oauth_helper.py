"""Local OAuth helper: obtains a LinkedIn access token and the member URN.

Run by the owner on their own machine (never in CI), roughly every 60 days.
Endpoints and scopes follow LinkedIn's official docs, checked on 2026-10-06:
- https://learn.microsoft.com/linkedin/shared/authentication/authorization-code-flow
- https://learn.microsoft.com/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
"""

from __future__ import annotations

import json
import os
import secrets
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import load_dotenv

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = ("openid", "profile", "w_member_social")
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
TOKEN_FILE = Path(".linkedin_token.json")
CALLBACK_TIMEOUT_SECONDS = 600


class OAuthError(RuntimeError):
    """Raised when any step of the OAuth flow fails."""


@dataclass(frozen=True)
class TokenResult:
    access_token: str
    expires_at: datetime
    scope: str
    member_urn: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "expires_at": self.expires_at.isoformat(),
                "scope": self.scope,
                "member_urn": self.member_urn,
            },
            indent=2,
        )


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(SCOPES),
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"


def parse_callback(path: str, expected_state: str) -> str:
    """Return the authorization code from the callback path, or raise OAuthError."""
    params = parse_qs(urlparse(path).query)
    if "error" in params:
        description = params.get("error_description", [""])[0]
        raise OAuthError(f"Authorization denied: {params['error'][0]} {description}".strip())
    if params.get("state", [None])[0] != expected_state:
        raise OAuthError("State mismatch in callback (possible CSRF); aborting.")
    code = params.get("code", [None])[0]
    if not code:
        raise OAuthError("Callback did not include an authorization code.")
    return code


def exchange_code(
    client: httpx.Client, code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    response = client.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
    )
    if response.status_code != 200:
        raise OAuthError(f"Token exchange failed ({response.status_code}): {response.text}")
    return response.json()


def fetch_member_urn(client: httpx.Client, access_token: str) -> str:
    response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise OAuthError(f"userinfo failed ({response.status_code}): {response.text}")
    return f"urn:li:person:{response.json()['sub']}"


def build_token_result(token_payload: dict, member_urn: str, now: datetime) -> TokenResult:
    return TokenResult(
        access_token=token_payload["access_token"],
        expires_at=now + timedelta(seconds=int(token_payload["expires_in"])),
        scope=token_payload.get("scope", ""),
        member_urn=member_urn,
    )


def wait_for_callback(redirect_uri: str) -> str:
    """Serve one local HTTP callback and return the raw request path."""
    parsed = urlparse(redirect_uri)
    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            if urlparse(self.path).path != parsed.path:
                self.send_response(404)
                self.end_headers()
                return
            captured["path"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

    class Server(HTTPServer):
        timed_out = False

        def handle_timeout(self) -> None:
            self.timed_out = True

    with Server((parsed.hostname or "localhost", parsed.port or 80), Handler) as server:
        server.timeout = CALLBACK_TIMEOUT_SECONDS
        while "path" not in captured:
            server.handle_request()
            if server.timed_out:
                raise OAuthError("Timed out waiting for the LinkedIn callback.")
    return captured["path"]


def build_http_client(proxy: str | None) -> httpx.Client:
    """HTTP client that ignores system proxy settings and uses `proxy` only if given.

    VPN clients may leave a system proxy setting that httpx cannot use (e.g. SOCKS4, or a
    stale port), so the proxy is configured explicitly via LINKEDIN_AUTH_PROXY instead.
    """
    return httpx.Client(timeout=30, proxy=proxy or None, trust_env=False)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise OAuthError(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


def main() -> None:
    load_dotenv()
    client_id = _require_env("LINKEDIN_CLIENT_ID")
    client_secret = _require_env("LINKEDIN_CLIENT_SECRET")
    redirect_uri = os.environ.get("LINKEDIN_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    proxy = os.environ.get("LINKEDIN_AUTH_PROXY", "").strip() or None

    state = secrets.token_urlsafe(24)
    auth_url = build_authorization_url(client_id, redirect_uri, state)
    print("Opening LinkedIn in your browser. If it does not open, visit:\n")
    print(auth_url, "\n")
    webbrowser.open(auth_url)
    print(
        f"Waiting for LinkedIn to redirect to {redirect_uri} "
        f"(up to {CALLBACK_TIMEOUT_SECONDS // 60} min). Keep this terminal open."
    )

    code = parse_callback(wait_for_callback(redirect_uri), state)
    with build_http_client(proxy) as client:
        token_payload = exchange_code(client, code, client_id, client_secret, redirect_uri)
        member_urn = fetch_member_urn(client, token_payload["access_token"])

    result = build_token_result(token_payload, member_urn, datetime.now(UTC))
    TOKEN_FILE.write_text(result.to_json(), encoding="utf-8")
    print(f"Member URN : {result.member_urn}")
    print(f"Scopes     : {result.scope}")
    print(f"Expires at : {result.expires_at:%Y-%m-%d %H:%M} UTC")
    print(f"Token saved to {TOKEN_FILE} (git-ignored). Do not share it.")


if __name__ == "__main__":
    main()
