import json
import time
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "episodes.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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


def _run_with_timeout(fn, model, seconds):
    """Run fn(model) in a thread; raise TimeoutError if it takes longer than `seconds`."""
    box = {}

    def target():
        try:
            box["result"] = fn(model)
        except Exception as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"TIMEOUT after {seconds}s (no response from {model})")
    if "error" in box:
        raise box["error"]
    return box["result"]


def with_fallback(models, fn, retries: int = 3, label: str = "call", timeout: int = 90):
    """Try fn(model) for each model in order, retrying transient errors.

    - 404 / NOT_FOUND  -> model name is wrong or retired: skip to next model.
    - 429 / 503        -> rate limit or overload: wait longer, retry.
    - timeout          -> no response: retry, then next model.
    - anything else    -> short wait, retry.
    """
    last = None
    for model in models:
        for attempt in range(retries):
            started = time.time()
            log(f"[{label}] START {model} attempt {attempt + 1}/{retries}")
            try:
                result = _run_with_timeout(fn, model, timeout)
                log(f"[{label}] OK {model} in {time.time() - started:.1f}s")
                return result
            except Exception as e:  # noqa: BLE001
                last = e
                msg = str(e)
                log(f"[{label}] FAIL {model} attempt {attempt + 1}/{retries} "
                    f"after {time.time() - started:.1f}s: {msg[:240]}")
                if "404" in msg or "NOT_FOUND" in msg:
                    break
                transient = any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
                if attempt < retries - 1:
                    time.sleep((20 if transient else 5) * (attempt + 1))
    raise RuntimeError(f"[{label}] all models failed. Last error: {last}")
