import json

from app.auth import GoogleAuthConfig


def test_google_auth_reads_web_client_file(monkeypatch, tmp_path):
    client_file = tmp_path / "client.json"
    client_file.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "redirect_uris": ["https://example.test/auth/callback"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_FILE", str(client_file))
    monkeypatch.setenv("GOOGLE_ALLOWED_DOMAINS", "example.edu, @example.org")

    config = GoogleAuthConfig.from_env()

    assert config.enabled is True
    assert config.redirect_uri == "https://example.test/auth/callback"
    assert config.allows_user("student@example.edu", "example.edu") is True
    assert config.allows_user("student@example.edu", "example.net") is False
    assert config.allows_user("student@example.net", "example.edu") is False
    assert config.allows_user("student@sub.example.edu", "example.edu") is False


def test_google_auth_is_disabled_without_credentials(monkeypatch):
    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_CLIENT_FILE",
    ):
        monkeypatch.delenv(name, raising=False)

    assert GoogleAuthConfig.from_env().enabled is False
