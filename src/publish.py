"""Upload the finished video to your TikTok *inbox* as a draft (Content Posting API, scope video.upload).

Why inbox and not Direct Post: Direct Post needs a TikTok audit, and until then every post is private (SELF_ONLY).
The inbox/upload flow is not behind that gate: TikTok sends you a notification, you open it, add a sound if you
like, switch the AI-generated toggle, and tap Post. One tap per day.

Needs (as GitHub Actions secrets):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN   (see tools/tiktok_auth.py)
Optional:
  GH_PAT              fine-grained token with "Secrets: read and write" on this repo, used to store a rotated
                      refresh token (TikTok may return a new one on every refresh)
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID    to receive the caption on your phone (the video upload API cannot carry a caption)
"""
import base64
import os
import time
from pathlib import Path

import requests

API = "https://open.tiktokapis.com"
GITHUB_API = "https://api.github.com"
TELEGRAM_API = "https://api.telegram.org"

MB = 1024 * 1024
MAX_SINGLE_CHUNK = 64 * MB   # up to 64 MB can be sent as one chunk
CHUNK_SIZE = 10 * MB         # larger files: 10 MB chunks (the last one absorbs the remainder, max 128 MB)

STATUS_OK = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}


class PublishError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------ auth
def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> dict:
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={"client_key": client_key, "client_secret": client_secret,
              "grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    data = r.json() if r.content else {}
    if r.status_code != 200 or "access_token" not in data:
        raise PublishError(
            f"token refresh failed (HTTP {r.status_code}): {data.get('error')} - {data.get('error_description')}. "
            "If the refresh token expired (365 days) or was revoked, run tools/tiktok_auth.py again."
        )
    if "video.upload" not in str(data.get("scope", "")):
        raise PublishError(f"token does not include video.upload (scopes: {data.get('scope')}). Re-authorize.")
    return data


def _encrypt_for_github(public_key_b64: str, value: str) -> str:
    """Sealed-box encryption exactly as documented by GitHub for the Actions secrets API."""
    from nacl import encoding, public  # PyNaCl

    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    return base64.b64encode(public.SealedBox(pk).encrypt(value.encode("utf-8"))).decode("utf-8")


def update_github_secret(name: str, value: str) -> bool:
    """Store `value` as repo secret `name`. Needs GH_PAT and GITHUB_REPOSITORY. Returns True on success."""
    pat, repo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    if not (pat and repo):
        return False
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    k = requests.get(f"{GITHUB_API}/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=30)
    k.raise_for_status()
    key = k.json()
    body = {"encrypted_value": _encrypt_for_github(key["key"], value), "key_id": key["key_id"]}
    r = requests.put(f"{GITHUB_API}/repos/{repo}/actions/secrets/{name}", headers=headers, json=body, timeout=30)
    r.raise_for_status()
    return True


def get_access_token() -> str:
    env = {k: os.environ.get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise PublishError(f"missing secrets: {', '.join(missing)}")
    tok = refresh_access_token(env["TIKTOK_CLIENT_KEY"], env["TIKTOK_CLIENT_SECRET"], env["TIKTOK_REFRESH_TOKEN"])
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != env["TIKTOK_REFRESH_TOKEN"]:
        try:
            saved = update_github_secret("TIKTOK_REFRESH_TOKEN", new_refresh)
        except Exception as e:  # noqa: BLE001
            saved = False
            print(f"[publish] could not store the rotated refresh token: {str(e)[:200]}")
        if saved:
            print("[publish] TikTok rotated the refresh token; TIKTOK_REFRESH_TOKEN secret updated.")
        else:
            print("::warning::TikTok returned a NEW refresh token but it could not be saved. Add a GH_PAT secret "
                  "(see README) or re-run tools/tiktok_auth.py if the next run fails.")
    return tok["access_token"]


# ------------------------------------------------------------------------------------------ upload
def _plan_chunks(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) following TikTok's chunk rules."""
    if size <= MAX_SINGLE_CHUNK:
        return size, 1  # whole file in one request (also required for files < 5 MB)
    return CHUNK_SIZE, size // CHUNK_SIZE  # floor; the remainder is merged into the final chunk


def _put_with_retry(url: str, headers: dict, data: bytes, tries: int = 3) -> requests.Response:
    last = None
    for attempt in range(tries):
        r = requests.put(url, headers=headers, data=data, timeout=300)
        if r.status_code < 500:
            return r
        last = f"HTTP {r.status_code}"
        time.sleep(5 * (attempt + 1))
    raise PublishError(f"upload chunk failed after retries ({last})")


def upload_to_inbox(video_path: str | Path, access_token: str) -> str:
    """Send the video to the creator's inbox. Returns publish_id."""
    path = Path(video_path)
    size = path.stat().st_size
    chunk_size, total = _plan_chunks(size)

    r = requests.post(
        f"{API}/v2/post/publish/inbox/video/init/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                              "chunk_size": chunk_size, "total_chunk_count": total}},
        timeout=60,
    )
    body = r.json() if r.content else {}
    err = (body.get("error") or {})
    if r.status_code != 200 or err.get("code") not in (None, "ok"):
        code = err.get("code", r.status_code)
        hint = {
            "spam_risk_too_many_pending_share": " (too many unfinished drafts: post or delete the old ones in your TikTok inbox)",
            "scope_not_authorized": " (re-run tools/tiktok_auth.py and approve video.upload)",
            "access_token_invalid": " (token problem: check TIKTOK_* secrets)",
            "rate_limit_exceeded": " (max 6 init requests per minute)",
        }.get(code, "")
        raise PublishError(f"init failed: {code}: {err.get('message', '')}{hint}")
    data = body["data"]
    publish_id, upload_url = data["publish_id"], data["upload_url"]

    with open(path, "rb") as f:
        for i in range(total):
            start = i * chunk_size
            n = size - start if i == total - 1 else chunk_size  # last chunk takes the remainder
            blob = f.read(n)
            resp = _put_with_retry(upload_url, {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(blob)),
                "Content-Range": f"bytes {start}-{start + len(blob) - 1}/{size}",
            }, blob)
            expected = 201 if i == total - 1 else 206
            if resp.status_code != expected:
                raise PublishError(f"chunk {i + 1}/{total}: expected HTTP {expected}, got {resp.status_code}: {resp.text[:200]}")
    return publish_id


def wait_for_status(publish_id: str, access_token: str, timeout: int = 300, poll: float = 5.0) -> str:
    """Poll until TikTok has put the draft in the inbox (or failed). Returns the final status."""
    deadline, status = time.time() + timeout, "UNKNOWN"
    while time.time() < deadline:
        r = requests.post(
            f"{API}/v2/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": publish_id}, timeout=30,
        )
        data = (r.json() or {}).get("data", {}) if r.content else {}
        status = data.get("status", "UNKNOWN")
        if status in STATUS_OK:
            return status
        if status == "FAILED":
            raise PublishError(f"TikTok rejected the upload: {data.get('fail_reason', 'unknown reason')}")
        time.sleep(poll)
    raise PublishError(f"timed out waiting for TikTok (last status: {status})")


# ------------------------------------------------------------------------------------------ notify
def notify(text: str) -> None:
    """Send `text` to Telegram (optional) and append it to the GitHub Actions run summary."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(f"{TELEGRAM_API}/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000]}, timeout=30).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[notify] telegram failed: {str(e)[:150]}")


def publish_episode(video_path: str | Path, meta: dict) -> dict:
    """Upload as a draft and tell the user how to finish. Raises PublishError on failure."""
    token = get_access_token()
    publish_id = upload_to_inbox(video_path, token)
    status = wait_for_status(publish_id, token)
    print(f"[publish] uploaded to TikTok inbox: {publish_id} ({status})")
    notify(
        f"TikTok draft ready (episode {meta['episode']}).\n"
        "Open TikTok -> Inbox -> tap the notification -> add a trending sound -> turn on 'AI-generated content' "
        "if it applies -> Post.\n\n"
        f"CAPTION (copy/paste):\n{meta['caption']}"
    )
    return {"status": status, "publish_id": publish_id}
