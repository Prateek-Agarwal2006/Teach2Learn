from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def fetch(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    origin: str | None = None,
) -> tuple[int, dict[str, str], str]:
    headers = {"User-Agent": "Teach2Learn security smoke test"}
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        response = opener.open(request, timeout=15)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read().decode("utf-8", errors="replace")
    with response:
        return response.status, dict(response.headers.items()), response.read().decode("utf-8", errors="replace")


def main() -> None:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "https://learnbyteaching.sasanktumpati.com").rstrip("/")
    opener = urllib.request.build_opener(NoRedirect)
    results: dict[str, object] = {}

    for path in ("/health", "/docs", "/redoc", "/openapi.json", "/api/catalog"):
        status, headers, body = fetch(opener, base_url, path)
        results[path] = {
            "status": status,
            "minimal_health": body.strip() == '{"status":"ok"}' if path == "/health" else None,
            "cors_exposed": any(key.lower() == "access-control-allow-origin" for key in headers),
        }

    status, _, _ = fetch(opener, base_url, "/logout", method="POST", data=b"", origin="https://attacker.example")
    results["cross_origin_post"] = status
    status, _, _ = fetch(opener, base_url, "/logout", method="POST", data=b"")
    results["missing_origin_post"] = status
    status, _, _ = fetch(opener, base_url, "/logout", method="POST", data=b"x" * 262145, origin=base_url)
    results["oversized_post"] = status

    status, headers, _ = fetch(opener, base_url, "/auth/google")
    cookie = next((value for key, value in headers.items() if key.lower() == "set-cookie"), "")
    results["oauth_cookie"] = {
        "status": status,
        "host_prefix": cookie.startswith("__Host-t2l_session="),
        "secure": "secure" in cookie.lower(),
        "http_only": "httponly" in cookie.lower(),
        "same_site_lax": "samesite=lax" in cookie.lower(),
    }
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
