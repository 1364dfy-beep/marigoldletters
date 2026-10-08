import json
import os
import random

from google import genai
from google.genai import types

from .util import with_fallback

SYSTEM_HORROR = (
    "You are the head writer of a faceless short-form horror channel. "
    "You write original stories meant to be HEARD, not read. "
    "You always follow the series bible and always return valid JSON only."
)
SYSTEM_QUOTES = (
    "You are the head writer of a warm, emotionally precise short-form text channel about love, "
    "self-worth and character. Your writing is specific, tender and 100% original (never a known quote). "
    "You always follow the channel bible and always return valid JSON only."
)


def _arc_block(settings: dict, arc: dict | None, part: int, parts: int, state: dict) -> str:
    if part == 1:
        return (
            f"This is PART 1 of {parts} of a NEW story arc.\n"
            f"Setting inspiration: {random.choice(settings['settings_pool'])}.\n"
            f"Narrative device: {random.choice(settings['devices_pool'])}.\n"
            "Invent the arc: arc_title (short, evocative) and arc_premise "
            "(2-3 sentences describing where the full arc is heading, including the final reveal). "
            f"End on a cliffhanger that makes people want part 2 of {parts}."
        )
    prev = [e for e in state["episodes"] if e.get("arc_title") == arc["title"]]
    prev_txt = "\n".join(f"- Part {e['part']}: {e['summary']}" for e in prev)
    if part == parts:
        ending = (
            "This is the FINAL part: resolve the central mystery, "
            "but leave one last unsettling detail in the final sentence."
        )
    else:
        ending = f"End on a cliffhanger that points toward part {part + 1} of {parts}."
    return (
        f"This is PART {part} of {parts} of the arc '{arc['title']}'.\n"
        f"Arc premise: {arc['premise']}\n"
        f"Previous parts:\n{prev_txt}\n"
        "Continue directly from the last part, same narrator, same place, same rules. "
        f"{ending}\n"
        "Return arc_title and arc_premise exactly as given above."
    )


_NARR_REQ = """HARD REQUIREMENTS:
- The episode is a list of 8-10 "scenes". Each scene has:
    "text": 1-3 sentences of narration for that story beat, and
    "image_prompt": a concrete picture of that beat for an image generator.
  Concatenated in order, all "text" fields form the full narration: {lo}-{hi} words in total,
  first person, plain spoken English, short sentences, written to be HEARD
  (no stage directions, no emojis, no hashtags, no headings, no "Part X" labels).
- The very first sentence of scene 1 must be a hook that raises a question in the listener's mind.
- "image_prompt" rules: 15-35 words. Show an EMPTY place, an object, a doorway, a corridor, or a lone
  silhouette seen from far away or from behind. Mention the lighting and ONE unsettling detail.
  NEVER show faces, hands, readable text, signs, clocks, numbers or logos (image models draw them badly).
  Do NOT write style words like "cinematic" or "photo": the style is added automatically.
"""

_SLIDE_REQ = """HARD REQUIREMENTS:
- The episode is a SILENT TEXT SLIDESHOW of 10-12 slides, read on a phone over music. Each slide has:
    "text": 1-3 short punchy sentences (max 22 words) shown on screen, and
    "image_prompt": a concrete picture of that beat, used as the slide background.
  All "text" fields in order tell the whole story: {lo}-{hi} words in total, first person, plain English,
  written to be READ at a glance (no emojis, no hashtags, no headings, no stage directions, no "Part X" labels).
- Slide 1 must be a hook that raises a question in the reader's mind. The last slide ends on the
  cliffhanger / final chill.
- "image_prompt" rules: 15-35 words. Show an EMPTY place, an object, a doorway, a corridor, or a lone
  silhouette seen from far away or from behind. Mention the lighting and ONE unsettling detail.
  NEVER show faces, hands, readable text, signs, clocks, numbers or logos (image models draw them badly).
  Do NOT write style words like "cinematic" or "photo": the style is added automatically.
"""


def _word_range(settings: dict) -> tuple[int, int]:
    prof = settings["profiles"][settings["content"]]
    if settings.get("format") == "slideshow":
        lo, hi = prof["words"]
    else:
        lo, hi = settings["narration_words"]
    return lo, hi


def _build_prompt(bible, settings, state, ep_num, arc, part, parts) -> str:
    lo, hi = _word_range(settings)
    recent = "\n".join(
        f"- #{e['num']} \"{e['title']}\": {e['summary']}" for e in state["episodes"][-6:]
    ) or "(none yet)"
    req = (_SLIDE_REQ if settings.get("format") == "slideshow" else _NARR_REQ).format(
        lo=lo, hi=hi, part=part, parts=parts)
    return f"""SERIES BIBLE:
{bible}

TASK: Write episode #{ep_num}.
{_arc_block(settings, arc, part, parts, state)}

{req}
- Original story only. No real people, brands or existing franchises. No gore, sex, harm to children, or self-harm.
- Do not reuse plots or images from the recent episodes below.
- "caption": one punchy line for the TikTok caption (include "Part {part}/{parts}").
- "hashtags": 4-6 relevant tags WITHOUT the # sign.
- "summary": 2 sentences describing what happened in this episode, for continuity.

RECENT EPISODES (do not repeat):
{recent}

Return ONLY a JSON object with keys:
arc_title, arc_premise, title, scenes, caption, hashtags, summary"""


def _pick_template_and_theme(prof: dict, state: dict, ep_num: int) -> tuple[dict, str]:
    tpl = prof["templates"][(ep_num - 1) % len(prof["templates"])]
    recent = {e.get("theme") for e in state["episodes"][-4:]}
    options = [th for th in prof["themes"] if th not in recent] or prof["themes"]
    return tpl, random.choice(options)


def _build_quotes_prompt(bible, settings, state, ep_num, prof, tpl, theme) -> str:
    lo, hi = _word_range(settings)
    recent = "\n".join(
        f"- #{e['num']} [{e.get('template', '?')} / {e.get('theme', '?')}] \"{e['title']}\": {e['summary']}"
        for e in state["episodes"][-8:]
    ) or "(none yet)"
    return f"""CHANNEL BIBLE:
{bible}

TASK: Write episode #{ep_num}.
FORMAT: {tpl['id'].upper()}. {tpl['how']}
THEME: {theme}

HARD REQUIREMENTS:
- The episode is a SILENT TEXT SLIDESHOW of 10-12 slides (about 65 seconds), read on a phone over soft music.
  Each slide has:
    "text": 1-3 short sentences (max 20 words) shown on screen, and
    "image_prompt": a 2-4 word English search phrase for a background PHOTO on a stock-photo site.
  All "text" fields in order form the whole piece: {lo}-{hi} words in total.
- Slide 1 is a scroll-stopping hook (specific, emotional, makes the reader need to know the rest).
  Put the single most quotable line on slide 9 or 10. The last slide lands softly, with warmth.
- 100% original wording. NEVER quote or paraphrase famous quotes, songs, books or people. No attributions.
  No emojis, no hashtags, no headings, no stage directions, no slide numbers in the text.
- "image_prompt" rules: concrete and photographable, matching the mood of that slide. Draw from:
  {prof['photo_moods']}.
  Every slide gets a DIFFERENT phrase. No faces needed (prefer silhouettes, hands, backs, nature).
  Never ask for text, quotes, signs, logos or brands.
- "title": a short internal title (not shown on screen).
- "caption": ONE line for the TikTok caption that ends with a question or a "send this to..." nudge.
- "hashtags": 5 relevant tags WITHOUT the # sign (mix broad and niche).
- "summary": 1-2 sentences naming the central idea and the hook line, so future episodes avoid repeating it.

RECENT EPISODES (do not repeat their ideas, hooks or images):
{recent}

Return ONLY a JSON object with keys:
title, scenes, caption, hashtags, summary"""


def _parse(text: str | None, lo: int, hi: int, standalone: bool = False) -> dict:
    if not text:
        raise ValueError("empty response (possibly blocked by safety filters)")
    data = json.loads(text)
    required = ["title", "scenes", "caption", "hashtags", "summary"]
    if not standalone:
        required += ["arc_title", "arc_premise"]
    for key in required:
        if key not in data:
            raise ValueError(f"missing key: {key}")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or not 6 <= len(scenes) <= 14:
        raise ValueError(f"expected 6-14 scenes, got {len(scenes) if isinstance(scenes, list) else scenes!r}")
    clean = []
    for sc in scenes:
        txt, img = str(sc.get("text", "")).strip(), str(sc.get("image_prompt", "")).strip()
        if not txt or not img:
            raise ValueError("scene without text or image_prompt")
        clean.append({"text": txt, "image_prompt": img})
    data["scenes"] = clean
    data["narration"] = " ".join(sc["text"] for sc in clean)
    n = len(data["narration"].split())
    if n < int(lo * 0.8) or n > int(hi * 1.25):
        raise ValueError(f"narration has {n} words, expected {lo}-{hi}")
    data["hashtags"] = [str(h).lstrip("#") for h in data["hashtags"]][:6]
    return data


def _plan_photos(prof: dict, state: dict, n: int) -> list[str] | None:
    """Pick one search phrase per slide from prof['photo_pool'] (muted -> calm -> golden, so the video warms up).
    Phrases used in the last 3 episodes are avoided, and no phrase repeats inside a video. This replaces the
    model's own image phrases, which kept converging on the same few subjects (coffee cup, rainy window...)."""
    pool = prof.get("photo_pool")
    if not pool or n < 1:
        return None
    recent = {q for h in state.get("photo_history", [])[-3:] for q in h}
    chosen: list[str] = []
    for i in range(n):
        pos = i / max(n - 1, 1)
        cat = "muted" if pos < 0.34 else ("calm" if pos < 0.72 else "golden")
        options = list(pool.get(cat) or [])
        fresh = [q for q in options if q not in recent and q not in chosen]
        options = fresh or [q for q in options if q not in chosen] or options
        if not options:
            return None
        chosen.append(random.choice(options))
    return chosen


def generate_episode(bible, settings, state, ep_num, arc, part, parts) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prof = settings["profiles"][settings["content"]]
    lo, hi = _word_range(settings)
    standalone = prof["series"] == "standalone"
    extra = {}
    if standalone:
        tpl, theme = _pick_template_and_theme(prof, state, ep_num)
        prompt = _build_quotes_prompt(bible, settings, state, ep_num, prof, tpl, theme)
        system = SYSTEM_QUOTES
        extra = {"template": tpl["id"], "theme": theme}
    else:
        prompt = _build_prompt(bible, settings, state, ep_num, arc, part, parts)
        system = SYSTEM_HORROR

    def run(model: str) -> dict:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=1.0,
                response_mime_type="application/json",
            ),
        )
        data = _parse(resp.text, lo, hi, standalone)
        if standalone:
            data.setdefault("arc_title", extra["theme"])
            data.setdefault("arc_premise", "")
        return data

    data = with_fallback(settings["text_models"], run, label="script")
    data.update(extra)
    if standalone:
        plan = _plan_photos(prof, state, len(data["scenes"]))
        if plan:
            for sc, q in zip(data["scenes"], plan):
                sc["image_prompt"] = q
            state["photo_history"] = (state.get("photo_history", []) + [plan])[-10:]  # saved with the state
            print("[script] photo plan:", " | ".join(plan), flush=True)
    return data
