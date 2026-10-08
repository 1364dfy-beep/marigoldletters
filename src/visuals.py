"""Slide backgrounds. Two providers, chosen by the content profile:

pexels      real photos from Pexels (free key: PEXELS_API_KEY). Returns photographer credits.
cloudflare  AI illustrations via Cloudflare Workers AI (FLUX.1 schnell, free daily allowance).
            Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.

If a key is missing or a request fails, that slide reuses an earlier image (or a generated
background) so the pipeline never fails. (Pexels photos are never reused: no new photo -> gradient.)
"""
import base64
import os
import random
import subprocess
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
# generic warm, people-free fallbacks, tried (in rotation) when a slide's own search phrase finds nothing new
FALLBACK_QUERIES = [
    "soft pink flowers", "calm lake sunrise", "golden hour field", "misty hills dawn", "marigold flowers",
    "coffee cup window light", "open book candle", "rain on window", "wildflower meadow", "ocean sunset",
    "peony flowers", "golden wheat field", "sunlight through leaves", "folded blanket cozy",
]
SIMILAR_BITS = 10  # two photos whose 8x8 hashes differ in <= this many of 64 bits count as "the same picture"
MIN_LUMA = 100     # average brightness (0-255) below this = too dark/gloomy for a warm channel -> rejected
MAX_BLUE_RATIO = 1.25  # average blue / red above this = cold blue-grey photo -> rejected


def _pexels_search(query: str, key: str, page: int = 1) -> list[dict]:
    r = requests.get(
        PEXELS_SEARCH,
        headers={"Authorization": key},
        params={"query": query, "orientation": "portrait", "size": "large", "per_page": 30, "page": page},
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


def _analyze(path: str) -> tuple[int, float, float] | None:
    """(64-bit difference hash, average brightness 0-255, blue/red ratio) from a tiny 9x8 RGB decode by ffmpeg.
    The hash catches the same photo (or a near-identical shot) even when Pexels gives it another id.
    Returns None if the image cannot be analysed (then no filter is applied)."""
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=9:8:flags=area,format=rgb24", "-frames:v", "1",
             "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
        if len(raw) < 216:
            return None
        px = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, 216, 3)]
        gray = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if gray[row * 9 + col] > gray[row * 9 + col + 1] else 0)
        luma = sum(gray) / len(gray)
        red = sum(p[0] for p in px) / len(px)
        blue = sum(p[2] for p in px) / len(px)
        return bits, luma, blue / max(red, 1.0)
    except Exception:  # noqa: BLE001
        return None


def _too_similar(fp: int | None, seen: list[int]) -> bool:
    return fp is not None and any(bin(fp ^ o).count("1") <= SIMILAR_BITS for o in seen)


def _queries_for(q: str, i: int) -> list[str]:
    """The slide's phrase, its first two words, then rotating generic fallbacks (never the same list twice)."""
    out = [q, " ".join(q.split()[:2])]
    n = len(FALLBACK_QUERIES)
    out += [FALLBACK_QUERIES[(i * 3 + k) % n] for k in range(6)]
    return [x for x in dict.fromkeys(a for a in out if a)]


def pexels_photos(scenes: list[dict], workdir: Path) -> tuple[list[str | None], list[str]]:
    """One photo per slide, never repeating inside the video: unique photo id, preferably a different
    photographer, and not visually near-identical to an earlier slide. Photos that are too dark or cold blue
    are skipped (this channel is warm and golden). If nothing suitable can be found, the slide gets the soft
    gradient background instead of a repeat."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        print("[visuals] PEXELS_API_KEY not set -> soft gradient backgrounds only")
        return [None] * len(scenes), []
    used_ids: set[int] = set()
    used_people: set[str] = set()
    seen_fps: list[int] = []
    out: list[str | None] = []
    credits: list[str] = []
    for i, sc in enumerate(scenes):
        path = None
        q = sc["image_prompt"]
        for query in _queries_for(q, i):
            pool: list[dict] = []
            for page in (1, 2):
                try:
                    pool += _pexels_search(query, key, page)
                except Exception as e:  # noqa: BLE001
                    print(f"[visuals] search '{query}' failed: {str(e)[:150]}")
                    break
            pool = [p for p in pool if p["id"] not in used_ids]
            random.shuffle(pool)
            pool.sort(key=lambda p: p.get("photographer") in used_people)  # new photographers first (stable sort)
            tries = 0
            for photo in pool:
                if tries >= 14:
                    break
                dest = workdir / f"photo_{i}.jpg"
                if not any(_download(u, dest) for u in _photo_urls(photo)):
                    continue
                tries += 1
                used_ids.add(photo["id"])
                info = _analyze(str(dest))
                fp = info[0] if info else None
                if info and info[1] < MIN_LUMA:
                    print(f"[visuals] slide {i + 1}: skipped a too-dark photo of '{query}' (brightness {info[1]:.0f})")
                    continue
                if info and info[2] > MAX_BLUE_RATIO:
                    print(f"[visuals] slide {i + 1}: skipped a cold blue photo of '{query}' (blue/red {info[2]:.2f})")
                    continue
                if _too_similar(fp, seen_fps):
                    print(f"[visuals] slide {i + 1}: skipped a near-duplicate photo of '{query}'")
                    continue
                if fp is not None:
                    seen_fps.append(fp)
                used_people.add(photo.get("photographer", ""))
                credits.append(photo.get("photographer", "Unknown"))
                path = str(dest)
                break
            if path:
                break
        print(f"[visuals] slide {i + 1}/{len(scenes)}: '{q}' -> {'ok' if path else 'no new photo, gradient background'}")
        out.append(path)
        time.sleep(0.3)  # be polite to the API
    return out, sorted(set(credits))


# ======================================================================= dispatcher
def get_images(scenes: list[dict], prof: dict, settings: dict, workdir: Path):
    """Returns (image_paths, photographer_credits)."""
    if prof["image_provider"] == "pexels":
        return pexels_photos(scenes, workdir)
    return generate_scene_images(scenes, settings["image"], workdir), []
