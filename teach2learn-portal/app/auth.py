from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from authlib.integrations.starlette_client import OAuth


@dataclass(frozen=True, slots=True)
class GoogleAuthConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    allowed_domains: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "GoogleAuthConfig":
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        client_file = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
        redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()

        if client_file:
            payload = json.loads(Path(client_file).expanduser().read_text(encoding="utf-8"))
            web = payload.get("web") or {}
            client_id = client_id or str(web.get("client_id", "")).strip()
            client_secret = client_secret or str(web.get("client_secret", "")).strip()
            if not redirect_uri:
                redirect_uris = web.get("redirect_uris") or []
                redirect_uri = str(redirect_uris[0]).strip() if redirect_uris else ""

        domains = tuple(
            item.strip().lower().lstrip("@")
            for item in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",")
            if item.strip()
        )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            allowed_domains=domains,
        )

    def allows_user(self, email: str, hosted_domain: str) -> bool:
        if not self.allowed_domains:
            return True
        if "@" not in email:
            return False
        email_domain = email.lower().rsplit("@", 1)[-1]
        hosted_domain = hosted_domain.strip().lower().lstrip("@")
        return any(
            secrets.compare_digest(email_domain, allowed)
            and secrets.compare_digest(hosted_domain, allowed)
            for allowed in self.allowed_domains
        )


def build_oauth(config: GoogleAuthConfig) -> OAuth:
    oauth = OAuth()
    if config.enabled:
        oauth.register(
            name="google",
            client_id=config.client_id,
            client_secret=config.client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth
