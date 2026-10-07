#!/usr/bin/env python3
"""One-time helper: authorize your own TikTok account and get the REFRESH TOKEN for the GitHub secret.

Run it on your own computer (needs only `pip install requests`).

  1)  python tools/tiktok_auth.py url
        prints a TikTok authorization link. Open it, log in with the account you added as a Target User, approve.
        TikTok redirects you to your GitHub Pages callback page, which shows the code.
  2)  python tools/tiktok_auth.py exchange "<paste the full redirected URL, or just the code>"
        prints your refresh token. Save it as the GitHub secret TIKTOK_REFRESH_TOKEN.

Settings come from environment variables (or you are asked):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI  (the exact URI registered in the TikTok portal)
"""
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.upload"
STATE_FILE = Path(__file__).with_name(".tiktok_state")


def _cfg(name: str, secret: bool = False) -> str:
    v = os.environ.get(name)
    if not v:
        import getpass
        v = (getpass.getpass if secret else input)(f"{name}: ").strip()
    return v


def cmd_url() -> None:
    state = secrets.token_urlsafe(16)
    STATE_FILE.write_text(state)
    url = (f"{AUTH_URL}?client_key={quote(_cfg('TIKTOK_CLIENT_KEY'))}&scope={SCOPES}&response_type=code"
           f"&redirect_uri={quote(_cfg('TIKTOK_REDIRECT_URI'), safe='')}&state={state}")
    print("\nOpen this link in a browser where you are logged in to TikTok:\n\n" + url + "\n")


def cmd_exchange(pasted: str) -> None:
    pasted = pasted.strip()
    if "code=" in pasted:
        q = parse_qs(urlparse(pasted).query)
        code, state = (q.get("code", [""])[0], q.get("state", [""])[0])
    else:
        code, state = pasted, ""
    code = unquote(code)
    if not code:
        sys.exit("No code found. Paste the full URL you were redirected to.")
    if state and STATE_FILE.exists() and state != STATE_FILE.read_text().strip():
        sys.exit("The 'state' does not match the one we generated. Run the 'url' step again.")
    r = requests.post(TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, data={
        "client_key": _cfg("TIKTOK_CLIENT_KEY"), "client_secret": _cfg("TIKTOK_CLIENT_SECRET", secret=True),
        "code": code, "grant_type": "authorization_code", "redirect_uri": _cfg("TIKTOK_REDIRECT_URI"),
    }, timeout=30)
    data = r.json()
    if "refresh_token" not in data:
        sys.exit(f"Failed: {data.get('error')} - {data.get('error_description')} (codes expire in minutes; repeat the 'url' step)")
    print("\nScopes granted:", data.get("scope"))
    if "video.upload" not in data.get("scope", ""):
        print("WARNING: video.upload was not granted. Make sure the Content Posting API product is added to the app.")
    print("\nAdd these as GitHub repository secrets (Settings -> Secrets and variables -> Actions):")
    print("  TIKTOK_REFRESH_TOKEN =", data["refresh_token"])
    print(f"\n(refresh token valid for {int(data.get('refresh_expires_in', 0)) // 86400} days; the workflow renews it automatically.)")
    STATE_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "url":
        cmd_url()
    elif len(sys.argv) >= 3 and sys.argv[1] == "exchange":
        cmd_exchange(" ".join(sys.argv[2:]))
    else:
        print(__doc__)
