"""Slide backgrounds. Two providers, chosen by the content profile:

pexels      real photos from Pexels (free key: PEXELS_API_KEY). Returns photographer credits.
cloudflare  AI illustrations via Cloudflare Workers AI (FLUX.1 schnell, free daily allowance).
            Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.

If a key is missing or a request fails, that slide reuses an earlier image (or a generated
background) so the pipeline never fails.
"""
import base64
import os
import random
import time
from pathlib import Path

import requests


def _generate_one(prompt: str, cfg: dict, seed: int, account: str, token: str) -> bytes:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{cfg['model']}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"prompt": prompt, "steps": cfg.get("steps", 4), "seed": seed}
    last = None
    for attempt in range(3):
        r = requests.post(url, headers=headers, json=payload, timeout=120)
        if r.status_code == 400 and "seed" in payload:  # model/version without seed support
            payload.pop("seed")
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("image/"):
            return r.content
        data = r.json()
        b64 = (data.get("result") or {}).get("image")
        if not b64:
            raise RuntimeError(f"no image in response: {str(data)[:200]}")
        return base64.b64decode(b64)
    raise RuntimeError(last or "image generation failed")


def generate_scene_images(scenes: list[dict], cfg: dict, workdir: Path) -> list[str | None]:
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (account and token):
        print("[visuals] Cloudflare credentials not set -> generated dark backgrounds only")
        return [None] * len(scenes)

    style = " ".join(str(cfg["style_prefix"]).split())
    seed = random.randint(1, 2**31 - 1)  # same seed for the whole episode -> more coherent look
    out: list[str | None] = []
    exhausted = False
    for i, sc in enumerate(scenes):
        path = None
        if not exhausted:
            try:
                img = _generate_one(f"{style} {sc['image_prompt']}", cfg, seed, account, token)
                dest = workdir / f"scene_{i}.img"
                dest.write_bytes(img)
                path = str(dest)
                print(f"[visuals] scene {i + 1}/{len(scenes)} ok")
            except Exception as e:  # noqa: BLE001
                print(f"[visuals] scene {i + 1} failed: {str(e)[:200]}")
                if i > 0:
                    exhausted = True  # likely daily allowance; stop hammering the API
        if path is None:  # reuse the most recent good image (the pan direction will differ)
            path = next((p for p in reversed(out) if p), None)
        out.append(path)
    return out


# ======================================================================= Pexels (real photos)
PEXELS_SEARCH = "https://api.pexels.com/v1/search"
FALLBACK_QUERIES = ["soft pink flowers", "calm lake sunrise", "golden hour field", "misty mountains"]


def _pexels_search(query: str, key: str) -> list[dict]:
    r = requests.get(
        PEXELS_SEARCH,
        headers={"Authorization": key},
        params={"query": query, "orientation": "portrait", "size": "large", "per_page": 15},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("photos", [])


def _download(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=60) as dl:
            dl.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in dl.iter_content(1 << 20):
                    f.write(chunk)
        return dest.stat().st_size > 20_000
    except Exception as e:  # noqa: BLE001
        print(f"[visuals] download failed: {str(e)[:120]}")
        return False


def _photo_urls(photo: dict) -> list[str]:
    """Best-first: a 1080x1920 crop from Pexels' image CDN, then progressively plainer sizes."""
    src = photo.get("src", {})
    urls = []
    if src.get("original"):
        urls.append(f"{src['original']}?auto=compress&cs=tinysrgb&fit=crop&w=1080&h=1920")
    urls += [src.get(k) for k in ("portrait", "large2x", "large", "original") if src.get(k)]
    return urls


def pexels_photos(scenes: list[dict], workdir: Path) -> tuple[list[str | None], list[str]]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        print("[visuals] PEXELS_API_KEY not set -> soft gradient backgrounds only")
        return [None] * len(scenes), []
    used: set[int] = set()
    out: list[str | None] = []
    credits: list[str] = []
    for i, sc in enumerate(scenes):
        path = None
        q = sc["image_prompt"]
        # try the requested phrase, then its first two words, then generic romantic fallbacks
        attempts = [q, " ".join(q.split()[:2]), FALLBACK_QUERIES[i % len(FALLBACK_QUERIES)]]
        for query in dict.fromkeys(a for a in attempts if a):
            try:
                photos = [p for p in _pexels_search(query, key) if p["id"] not in used]
            except Exception as e:  # noqa: BLE001
                print(f"[visuals] search '{query}' failed: {str(e)[:150]}")
                continue
            random.shuffle(photos)
            for photo in photos[:8]:
                dest = workdir / f"photo_{i}.jpg"
                if any(_download(u, dest) for u in _photo_urls(photo)):
                    used.add(photo["id"])
                    path = str(dest)
                    credits.append(photo.get("photographer", "Unknown"))
                    break
            if path:
                break
        if path is None:  # reuse the previous good photo (the zoom direction will differ)
            path = next((p for p in reversed(out) if p), None)
        print(f"[visuals] slide {i + 1}/{len(scenes)}: '{q}' -> {'ok' if path else 'gradient fallback'}")
        out.append(path)
        time.sleep(0.3)  # be polite to the API
    return out, sorted(set(credits))


# ======================================================================= dispatcher
def get_images(scenes: list[dict], prof: dict, settings: dict, workdir: Path):
    """Returns (image_paths, photographer_credits)."""
    if prof["image_provider"] == "pexels":
        return pexels_photos(scenes, workdir)
    return generate_scene_images(scenes, settings["image"], workdir), []
