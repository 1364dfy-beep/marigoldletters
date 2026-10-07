"""Generate one episode.

content: quotes (default)  -> text slides over Pexels photos + warm generated music
content: horror            -> serial horror stories over AI illustrations (slideshow or narrated)
"""
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import assemble, captions, music, publish, script_gen, timeline, tts, visuals
from .util import ROOT, load_bible, load_settings, load_state, profile, save_state


def _hud(prof: dict, s: dict, v: dict, part: int, parts: int) -> dict | None:
    if prof["hud"] == "brand":
        return {"style": "brand", "text": prof["channel_name"]}
    if prof["hud"] == "rec":
        return {"style": "rec", "time": v["hud_time"], "right": f"{prof['channel_name']}  PT {part}/{parts}"}
    return None


def _slideshow(ep, s, prof, v, work, part, parts, ep_num):
    cfg = s["slideshow"]
    total = round(random.uniform(*cfg["target_seconds"]), 1)
    durs = timeline.slide_durations(ep["scenes"], total, cfg["reading_wps"], cfg["min_slide_seconds"])
    reveals = [timeline.reveal_offsets(captions.split_sentences(sc["text"]), d)
               for sc, d in zip(ep["scenes"], durs)]
    cta = prof["cta"]
    if prof["series"] == "arcs":
        cta = f"FOLLOW FOR PART {part + 1}" if part < parts else "FOLLOW FOR THE NEXT STORY"
    captions.write_slides_ass(ep["scenes"], durs, reveals, str(work / "captions.ass"),
                              v["width"], v["height"], s["captions"], _hud(prof, s, v, part, parts),
                              total, cta, prof["slide"])

    images, credits = visuals.get_images(ep["scenes"], prof, s, work)
    bg = assemble.build_background(images, durs, work, v, dim=prof["dim"],
                                   look=prof["look"], transition=prof["transition"])

    track = assemble.pick_music(ROOT / "assets" / "music")  # your own licensed tracks win
    if track:
        info = {"track": Path(track).name}
    else:
        track = str(work / "music.wav")
        info = music.generate(track, total + 1, seed=ep_num * 7919, mood=prof["music_mood"])
    out = ROOT / "output" / f"ep_{ep_num:03d}.mp4"
    assemble.final_mix(bg, None, "captions.ass", work, out, track, cfg["music_gain"], total)
    return out, total, info, credits


def _narrated(ep, s, prof, v, work, part, parts, ep_num):
    wav = str(work / "narration.wav")
    tts.synthesize(ep["narration"], wav, s)
    dur = assemble.duration(wav)
    print(f"Narration: {dur:.1f}s")
    if dur < 62:
        print("WARNING: shorter than 1 minute -> raise narration_words in config/settings.yaml.")
    words = captions.word_timings(wav, ep["narration"], dur, s["captions"]["whisper_model"])
    total = dur + v["tail_seconds"]
    captions.write_ass(words, str(work / "captions.ass"), v["width"], v["height"],
                       s["captions"], hud=_hud(prof, s, v, part, parts), total=total)
    durs = timeline.scene_durations(ep["scenes"], words, total)
    images, credits = visuals.get_images(ep["scenes"], prof, s, work)
    bg = assemble.build_background(images, durs, work, v, look=prof["look"])
    track = assemble.pick_music(ROOT / "assets" / "music")
    volume = v["music_volume"]
    custom = bool(track)
    if not track:
        track, volume = assemble.make_ambient(work / "ambient.wav", total + 2), v["ambient_volume"]
    out = ROOT / "output" / f"ep_{ep_num:03d}.mp4"
    assemble.final_mix(bg, wav, "captions.ass", work, out, track, volume, total)
    return out, dur, {"track": "custom" if custom else "generated ambient"}, credits


def main() -> None:
    s = load_settings()
    prof = profile(s)
    v = s["video"]
    state = load_state()

    ep_num = len(state["episodes"]) + 1
    standalone = prof["series"] == "standalone"
    parts = 1 if standalone else int(s["arc_parts"])
    arc = None if standalone else state.get("arc")
    part = 1 if standalone else (arc["part"] + 1 if arc and arc["part"] < arc["parts"] else 1)
    if part == 1:
        arc = None
    fmt = s.get("format", "slideshow")
    print(f"=== Episode {ep_num} | content: {s['content']} | format: {fmt}"
          + ("" if standalone else f" | arc part {part}/{parts}") + " ===")

    ep = script_gen.generate_episode(load_bible(prof["bible"]), s, state, ep_num, arc, part, parts)
    if not standalone and part > 1:  # keep arc identity stable regardless of what the model returned
        ep["arc_title"], ep["arc_premise"] = arc["title"], arc["premise"]
    print(f"Title: {ep['title']}  ({len(ep['narration'].split())} words, {len(ep['scenes'])} slides)")

    work = Path(tempfile.mkdtemp(prefix="ep_"))
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    run = _slideshow if fmt == "slideshow" else _narrated
    video_path, dur, audio_info, credits = run(ep, s, prof, v, work, part, parts, ep_num)

    caption = f"{ep['caption']} " + " ".join(f"#{h}" for h in ep["hashtags"])
    if credits:  # Pexels asks API users to credit Pexels and (where possible) the photographers
        caption += " | Photos: Pexels"
    meta = {
        "episode": ep_num, "content": s["content"], "format": fmt, "title": ep["title"],
        "template": ep.get("template"), "theme": ep.get("theme"),
        "part": part, "parts": parts,
        "caption": caption,
        "photo_credits": {"source": "Pexels (https://www.pexels.com)", "photographers": credits},
        "duration_seconds": round(dur, 1),
        "disclose_ai_generated": True,
        "audio": audio_info,
        "text": ep["narration"],
        "video_file": video_path.name,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path = out_dir / f"ep_{ep_num:03d}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    state["episodes"].append({
        "num": ep_num, "date": meta["created_utc"][:10], "arc_title": ep["arc_title"], "part": part,
        "title": ep["title"], "summary": ep["summary"],
        "template": ep.get("template"), "theme": ep.get("theme"),
    })
    if not standalone:
        state["arc"] = {"title": ep["arc_title"], "premise": ep["arc_premise"], "part": part, "parts": parts}
    save_state(state)
    print(f"Done: {video_path}")

    # Upload to the TikTok inbox as a draft. Everything above is already saved, so a failure here
    # never loses the episode: it just turns the run red and the video stays in the run's artifacts.
    pub = s.get("publish", {})
    if pub.get("enabled") and os.environ.get("TIKTOK_REFRESH_TOKEN"):
        try:
            meta["publish"] = publish.publish_episode(video_path, meta)
        except Exception as e:  # noqa: BLE001
            meta["publish"] = {"status": "FAILED", "error": str(e)[:500]}
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            publish.notify(f"TikTok upload FAILED for episode {ep_num}: {str(e)[:400]}\n"
                           "The video is still available in the run's Artifacts.")
            print(f"::error::TikTok upload failed: {e}")
            sys.exit(1)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print("[publish] skipped (publish.enabled is false or TIKTOK_REFRESH_TOKEN not set). "
              "Download the video from the run's Artifacts.")


if __name__ == "__main__":
    main()
