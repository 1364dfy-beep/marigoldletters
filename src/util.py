import json
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "episodes.json"


def load_settings() -> dict:
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))


def load_bible(name: str) -> str:
    return (ROOT / "config" / name).read_text(encoding="utf-8")


def profile(settings: dict) -> dict:
    """The active content profile (settings['profiles'][settings['content']])."""
    return settings["profiles"][settings["content"]]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"episodes": [], "arc": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def with_fallback(models, fn, retries: int = 3, label: str = "call"):
    """Try fn(model) for each model in order, retrying transient errors.

    - 404 / NOT_FOUND  -> model name is wrong or retired: skip to next model.
    - 429 / 503        -> rate limit or overload: wait longer, retry.
    - anything else    -> short wait, retry (TTS/LLM occasionally return junk).
    """
    last = None
    for model in models:
        for attempt in range(retries):
            try:
                return fn(model)
            except Exception as e:  # noqa: BLE001 - we really want to catch everything here
                last = e
                msg = str(e)
                print(f"[{label}] {model} attempt {attempt + 1}/{retries} failed: {msg[:240]}")
                if "404" in msg or "NOT_FOUND" in msg:
                    break
                transient = any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
                if attempt < retries - 1:
                    time.sleep((20 if transient else 5) * (attempt + 1))
    raise RuntimeError(f"[{label}] all models failed. Last error: {last}")
